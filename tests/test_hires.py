"""Tests for the focused Hi-Res authenticity verdict (hires.py).

Covers:
  * Pure verdict logic (derive_verdict / claims_hires) — no audio needed.
  * Integration on the bundled test files (genuine / upsampled / fake24 /
    lossy-cutoff / CD).

Run: .venv/bin/python -m unittest discover -s tests -v
"""

import unittest
from pathlib import Path

import numpy as np

from hifi_detector.core.audio_io import AudioData, read_audio
from hifi_detector.core.hires import (
    HiResIssue,
    claims_hires,
    derive_verdict,
    verify_hires,
    FAKE_THRESHOLD,
    SUSPICIOUS_THRESHOLD,
)

TESTDATA = Path(__file__).parent / "testdata"


def issue(kind: str, conf: float) -> HiResIssue:
    return HiResIssue(kind=kind, confidence=conf, headline=f"{kind}@{conf}", detail="d")


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------

class TestClaimsHiRes(unittest.TestCase):
    def test_cd_is_not_hires(self):
        self.assertFalse(claims_hires(44100, 16))
        self.assertFalse(claims_hires(22050, 16))
        self.assertFalse(claims_hires(32000, 16))

    def test_above_cd_is_hires(self):
        self.assertTrue(claims_hires(48000, 16))    # higher sample rate
        self.assertTrue(claims_hires(96000, 24))    # both higher
        self.assertTrue(claims_hires(44100, 24))    # higher bit depth only
        self.assertTrue(claims_hires(88200, 16))    # higher sample rate only


class TestDeriveVerdict(unittest.TestCase):
    def test_genuine_when_claim_and_no_issues(self):
        verdict, label, color, summary, conf = derive_verdict(True, [])
        self.assertEqual(verdict, "genuine_hires")
        self.assertEqual(color, "green")
        self.assertIn("未发现", summary)  # honest wording, not "certified"

    def test_fake_when_high_confidence_issue(self):
        verdict, *_ = derive_verdict(True, [issue("upsampled", 0.85)])
        self.assertEqual(verdict, "fake_hires")

    def test_suspicious_when_mid_confidence(self):
        mid = (FAKE_THRESHOLD + SUSPICIOUS_THRESHOLD) / 2
        verdict, *_ = derive_verdict(True, [issue("lossy_transcode", mid)])
        self.assertEqual(verdict, "suspicious")

    def test_low_confidence_stays_genuine(self):
        verdict, *_ = derive_verdict(True, [issue("lossy_transcode", 0.2)])
        self.assertEqual(verdict, "genuine_hires")

    def test_fake_threshold_boundary(self):
        verdict_at, *_ = derive_verdict(True, [issue("upsampled", FAKE_THRESHOLD)])
        verdict_below, *_ = derive_verdict(True, [issue("upsampled", FAKE_THRESHOLD - 0.01)])
        self.assertEqual(verdict_at, "fake_hires")
        self.assertEqual(verdict_below, "suspicious")

    def test_highest_confidence_drives_verdict(self):
        issues = [issue("lossy_transcode", 0.5), issue("upsampled", 0.9)]
        verdict, *_ = derive_verdict(True, issues)
        self.assertEqual(verdict, "fake_hires")

    def test_not_hires_when_no_claim(self):
        verdict, label, color, summary, _ = derive_verdict(False, [])
        self.assertEqual(verdict, "not_hires")
        self.assertIn("非 Hi-Res", summary)

    def test_not_hires_but_lossy_is_noted(self):
        verdict, _, _, summary, _ = derive_verdict(False, [issue("lossy_transcode", 0.8)])
        self.assertEqual(verdict, "not_hires")  # headline stays "not hi-res"
        self.assertIn("有损转码", summary)        # but the lossy finding is surfaced


# ---------------------------------------------------------------------------
# Integration on bundled test files
# ---------------------------------------------------------------------------

class TestVerifyHiResIntegration(unittest.TestCase):
    def _verify(self, name):
        path = TESTDATA / name
        if not path.exists():
            self.skipTest(f"missing test file: {name}")
        return verify_hires(read_audio(path))

    def test_genuine_hires_files_pass(self):
        for name in ("01_genuine_96k_24bit.wav", "07_genuine_192k_24bit.wav"):
            with self.subTest(name=name):
                rep = self._verify(name)
                self.assertTrue(rep.claims_hires)
                self.assertEqual(rep.verdict, "genuine_hires")
                self.assertEqual(rep.issues, [])

    def test_upsampled_files_are_fake(self):
        # 03: typical CD (44.1k) upsample -> clearly fake.
        rep = self._verify("03_upsampled_44k_to_96k_24bit.wav")
        self.assertEqual(rep.verdict, "fake_hires")
        self.assertIn("upsampled", [i.kind for i in rep.issues])
        # 06: 22.05k source with only ~10k bandwidth -> no clear brickwall at
        # CD Nyquist, so it is reported as "suspicious" (conservative, to avoid
        # false positives on quiet genuine hi-res). Must still flag upsampling.
        rep = self._verify("06_extreme_upsampled_22k_to_192k.wav")
        self.assertIn(rep.verdict, ("fake_hires", "suspicious"))
        self.assertIn("upsampled", [i.kind for i in rep.issues])

    def test_fake_24bit_is_fake(self):
        rep = self._verify("04_fake24bit_padded.wav")
        self.assertEqual(rep.verdict, "fake_hires")
        self.assertIn("fake_bitdepth", [i.kind for i in rep.issues])

    def test_mp3_cutoff_is_not_hires_but_lossy(self):
        # 05 is 16/44.1 (not claiming hi-res) but is a lossy transcode.
        rep = self._verify("05_mp3_sourced_cutoff.flac")
        self.assertFalse(rep.claims_hires)
        self.assertEqual(rep.verdict, "not_hires")
        self.assertIn("lossy_transcode", [i.kind for i in rep.issues])

    def test_genuine_cd_is_not_hires_and_clean(self):
        rep = self._verify("02_cd_44k_16bit.wav")
        self.assertFalse(rep.claims_hires)
        self.assertEqual(rep.verdict, "not_hires")
        self.assertEqual(rep.issues, [])

    def test_report_has_evidence_fields(self):
        rep = self._verify("03_upsampled_44k_to_96k_24bit.wav")
        # Upsampled file has (near) no ultrasonic content — that's the evidence.
        self.assertLess(rep.hf_energy_ratio, 0.005)
        self.assertTrue(rep.hires_target)


# ---------------------------------------------------------------------------
# Synthetic-signal regression tests for the corrected detection logic
# ---------------------------------------------------------------------------

def _audio(mono, sr=96000, bits=24, sub="PCM_24"):
    """Build an in-memory stereo AudioData from a mono signal."""
    mono = np.clip(np.asarray(mono, dtype=np.float64), -0.95, 0.95)
    stereo = np.stack([mono, mono])
    return AudioData(
        samples=stereo, sample_rate=sr, channels=2,
        duration_s=len(mono) / sr, bit_depth=bits,
        format="WAV", subtype=sub, file_path="synthetic",
    )


class TestUpsamplingNoFalsePositives(unittest.TestCase):
    """P0-1: genuinely dark / band-limited hi-res recordings must NOT be
    condemned as upsampled fakes. 'Little ultrasonic content' is not evidence —
    only a brickwall at a plausible source Nyquist is."""

    SR = 96000

    def _n(self):
        return int(self.SR * 3.0)

    def test_pure_sine_is_genuine(self):
        t = np.arange(self._n()) / self.SR
        rep = verify_hires(_audio(0.5 * np.sin(2 * np.pi * 1000 * t)))
        self.assertEqual(rep.verdict, "genuine_hires")
        self.assertNotIn("upsampled", [i.kind for i in rep.issues])

    def test_dark_recording_is_genuine(self):
        # Content lowpassed well below CD Nyquist — like a dark acoustic master.
        from scipy.signal import butter, filtfilt
        b, a = butter(4, 18000 / (self.SR / 2), "low")
        rng = np.random.default_rng(1)
        dark = filtfilt(b, a, np.cumsum(rng.standard_normal(self._n())))
        dark = dark / np.max(np.abs(dark)) * 0.5
        rep = verify_hires(_audio(dark))
        self.assertEqual(rep.verdict, "genuine_hires")
        self.assertNotIn("upsampled", [i.kind for i in rep.issues])

    def test_full_bandwidth_is_genuine(self):
        rng = np.random.default_rng(2)
        rep = verify_hires(_audio(0.3 * rng.standard_normal(self._n())))
        self.assertEqual(rep.verdict, "genuine_hires")


class TestBrickwallUpsampleDetected(unittest.TestCase):
    """P0-2: upsamples that leave a brickwall (FFT / cheap resamplers) ARE caught
    robustly and deterministically."""

    def test_fft_resample_cd_upsample_is_fake(self):
        from scipy.signal import butter, filtfilt, resample
        sr_src, sr_dst = 44100, 96000
        n_src = int(sr_src * 3.0)
        # Pink (1/f) noise — the realistic spectral shape of music (matches the
        # bundled test data). Brown noise would be far too red here.
        rng = np.random.default_rng(3)
        nfft = 2 ** int(np.ceil(np.log2(n_src)))
        freqs = np.fft.rfftfreq(nfft, 1 / sr_src)
        mag = np.zeros_like(freqs)
        mag[1:] = 1.0 / np.sqrt(freqs[1:])
        spec = mag * np.exp(1j * rng.uniform(0, 2 * np.pi, len(mag)))
        pink = np.fft.irfft(spec, n=nfft)[:n_src]
        # Band-limit to 20 kHz (typical CD mastering), then FFT-resample to 96k.
        b, a = butter(8, 20000 / (sr_src / 2), "low")
        src = filtfilt(b, a, pink)
        src = src / np.max(np.abs(src)) * 0.5
        up = resample(src, int(len(src) * sr_dst / sr_src))
        rep = verify_hires(_audio(up, sr=sr_dst))
        # A steady-state tone lands in the moderate-confidence band; dynamic real
        # music (bundled file 03) reaches fake_hires. Either way it is DETECTED.
        self.assertIn(rep.verdict, ("fake_hires", "suspicious"))
        self.assertIn("upsampled", [i.kind for i in rep.issues])


class TestFake24BitRobustness(unittest.TestCase):
    """Points 3 & 4: level-independent, grid-tolerant fake-24-bit detection."""

    SR = 96000

    def _n(self):
        return int(self.SR * 2.0)

    def test_zero_padded_32768_is_fake(self):
        rng = np.random.default_rng(4)
        v = rng.integers(-30000, 30000, self._n())
        rep = verify_hires(_audio((v * 256) / 2 ** 23))
        self.assertEqual(rep.verdict, "fake_hires")
        self.assertIn("fake_bitdepth", [i.kind for i in rep.issues])

    def test_full_scale_32767_is_fake(self):
        # Point 4: a /32767 (full-scale) encoder must not evade detection.
        rng = np.random.default_rng(5)
        v = rng.integers(-30000, 30000, self._n())
        rep = verify_hires(_audio(v / 32767))
        self.assertEqual(rep.verdict, "fake_hires")
        self.assertIn("fake_bitdepth", [i.kind for i in rep.issues])

    def test_genuine_24bit_is_not_fake(self):
        rng = np.random.default_rng(6)
        int24 = rng.integers(-2 ** 22, 2 ** 22, self._n())
        rep = verify_hires(_audio(int24 / 2 ** 23))
        self.assertEqual(rep.verdict, "genuine_hires")
        self.assertNotIn("fake_bitdepth", [i.kind for i in rep.issues])

    def test_unquantized_float_not_misfiring(self):
        # Point 3: arbitrary float (not on any grid) must not hit the old 0.60
        # zero-tolerance boundary and be called fake.
        rng = np.random.default_rng(7)
        rep = verify_hires(_audio(0.3 * rng.standard_normal(self._n())))
        self.assertEqual(rep.verdict, "genuine_hires")
        self.assertNotIn("fake_bitdepth", [i.kind for i in rep.issues])


class TestSilenceGate(unittest.TestCase):
    """P1-1: digital silence carries no analyzable content -> 'undetermined',
    not a misleading 'genuine'."""

    def test_digital_silence_is_undetermined(self):
        rep = verify_hires(_audio(np.zeros(int(96000 * 2.0))))
        self.assertEqual(rep.verdict, "undetermined")
        self.assertEqual(rep.issues, [])
        self.assertEqual(rep.confidence, 0.0)

    def test_near_silence_is_undetermined(self):
        # ~ -130 dBFS: effectively empty.
        rep = verify_hires(_audio(np.full(int(96000 * 2.0), 1e-7)))
        self.assertEqual(rep.verdict, "undetermined")

    def test_quiet_but_real_is_analyzed(self):
        # A genuinely quiet (-50 dBFS) signal must still be analyzed, not gated.
        rng = np.random.default_rng(8)
        rep = verify_hires(_audio(0.003 * rng.standard_normal(int(96000 * 2.0))))
        self.assertNotEqual(rep.verdict, "undetermined")


class TestGenuineConfidenceCapped(unittest.TestCase):
    """P1-2: a 'genuine' verdict is 'no fake detected', not a certification —
    its confidence must stay well below certainty."""

    def test_genuine_confidence_capped(self):
        rng = np.random.default_rng(9)
        rep = verify_hires(_audio(0.3 * rng.standard_normal(int(96000 * 3.0))))
        self.assertEqual(rep.verdict, "genuine_hires")
        self.assertLessEqual(rep.confidence, 0.80)


if __name__ == "__main__":
    unittest.main(verbosity=2)
