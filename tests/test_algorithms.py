"""Algorithm unit tests for hifi-detector.

These tests calibrate the DSP algorithms against signals with *known*
answers, so regressions in the core math are caught automatically.

Run with either:
    .venv/bin/python -m unittest discover -s tests -v
    .venv/bin/python -m pytest tests/            (if pytest is installed)

What is covered:
  * DR14   — constant signal => DR0; constructed signals with a known
             peak/average ratio => exact DR; proof the meter is no longer
             capped at ~7 dB.
  * LUFS   — BS.1770-4 channel summation (identical/uncorrelated stereo is
             +3.01 dB over mono), linearity (+6 dB per x2), gating ignores
             silence, absolute sanity range.
  * LRA    — constant level => ~0 LU; two-level signal => large LRA.
  * TruePeak — sine true peak matches its amplitude.
  * Authenticity — regression on the bundled test files (genuine => clean,
             upsampled => suspicious, forgeries detected).
"""

import unittest
from pathlib import Path

import numpy as np

from hifi_detector.core.audio_io import AudioData, read_audio
from hifi_detector.core.dynamic_range import analyze_dynamic_range, _dr_for_channel
from hifi_detector.core.loudness import (
    analyze_loudness,
    _integrated_lufs,
    _loudness_range,
    _true_peak,
)
from hifi_detector.core.authenticity import analyze_authenticity
from hifi_detector.core.metadata import extract_metadata
from hifi_detector.core.quality import analyze_quality

SR = 48000
TESTDATA = Path(__file__).parent / "testdata"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sine(freq: float, dur: float, amp: float = 1.0, sr: int = SR) -> np.ndarray:
    t = np.arange(int(dur * sr)) / sr
    return amp * np.sin(2 * np.pi * freq * t)


def make_audio(samples: np.ndarray, sr: int = SR, bit_depth: int = 24) -> AudioData:
    if samples.ndim == 1:
        samples = samples[np.newaxis, :]
    return AudioData(
        samples=samples.astype(np.float64),
        sample_rate=sr,
        channels=samples.shape[0],
        duration_s=samples.shape[1] / sr,
        bit_depth=bit_depth,
        format="WAV",
        subtype="PCM_24",
        file_path=Path("synthetic.wav"),
    )


def block_signal(loud_frac: float, quiet_amp: float, n_win: int = 120, seed: int = 0):
    """Build a signal of n_win half-second blocks with controlled per-block RMS.

    Returns (signal, expected_dr) where expected_dr is the analytic
    peak-minus-average DR: 20*log10(peak_rms / overall_rms).
    """
    win = int(0.5 * SR)
    t = np.arange(win) / SR
    n_loud = max(1, int(round(n_win * loud_frac)))
    amps = np.array([1.0] * n_loud + [quiet_amp] * (n_win - n_loud))
    np.random.default_rng(seed).shuffle(amps)
    # Each block is a sine scaled so its RMS is proportional to `amp`.
    sig = np.concatenate([a * np.sin(2 * np.pi * 1000 * t) / np.sqrt(2) for a in amps])
    # The constant scale factor cancels in the peak/average ratio.
    expected = 20 * np.log10(1.0 / np.sqrt(np.mean(amps ** 2)))
    return sig, expected


# ---------------------------------------------------------------------------
# DR14
# ---------------------------------------------------------------------------

class TestDynamicRange(unittest.TestCase):
    def test_constant_signal_is_dr_zero(self):
        """A constant-amplitude signal has no dynamics => DR ~ 0."""
        a = make_audio(sine(1000, 10.0, amp=0.5))
        dr = analyze_dynamic_range(a).dr_precise_avg_db
        self.assertAlmostEqual(dr, 0.0, delta=0.2)

    def test_known_dynamic_range(self):
        """Constructed signals must match the analytic peak-minus-average DR."""
        win = int(0.5 * SR)
        cases = [(0.20, 0.0), (0.10, 0.0), (0.05, 0.0), (0.02, 0.0), (0.01, 0.001)]
        for loud_frac, quiet in cases:
            with self.subTest(loud_frac=loud_frac, quiet=quiet):
                sig, expected = block_signal(loud_frac, quiet, n_win=120)
                got = _dr_for_channel(sig, 120, win)["dr_precise"]
                self.assertAlmostEqual(got, expected, delta=0.1)

    def test_not_capped_at_7dB(self):
        """A dynamic signal (sparse peaks) must exceed the old ~6.99 dB cap."""
        win = int(0.5 * SR)
        sig, expected = block_signal(0.02, 0.0, n_win=200, seed=2)  # ~17.8 dB
        got = _dr_for_channel(sig, 200, win)["dr_precise"]
        self.assertGreater(got, 12.0)
        self.assertAlmostEqual(got, expected, delta=0.1)

    def test_official_is_rounded_channel_mean(self):
        """Official DR = round(mean of per-channel precise DR)."""
        sig, expected = block_signal(0.05, 0.0, n_win=120)
        stereo = np.vstack([sig, sig])  # identical channels
        rep = analyze_dynamic_range(make_audio(stereo))
        self.assertEqual(rep.dr_official, int(round(expected)))
        self.assertAlmostEqual(rep.dr_precise_avg_db, expected, delta=0.1)

    def test_too_short_returns_na(self):
        a = make_audio(sine(1000, 0.2, amp=0.5))  # < 2 windows
        rep = analyze_dynamic_range(a)
        self.assertEqual(rep.rating, "N/A")


# ---------------------------------------------------------------------------
# LUFS (BS.1770-4)
# ---------------------------------------------------------------------------

class TestIntegratedLoudness(unittest.TestCase):
    def test_identical_stereo_is_plus_3dB_over_mono(self):
        """BS.1770 sums channel powers: identical L=R => +3.01 dB over mono.

        The old downmix-then-square code gave 0 dB here (the bug).
        """
        x = sine(1000, 4.0, amp=0.3)
        mono = _integrated_lufs(x[np.newaxis, :], SR)
        stereo = _integrated_lufs(np.vstack([x, x]), SR)
        self.assertAlmostEqual(stereo - mono, 10 * np.log10(2), delta=0.05)

    def test_uncorrelated_stereo_is_plus_3dB_over_one_channel(self):
        """Equal-power uncorrelated L/R => summed power is 2x one channel."""
        rng = np.random.default_rng(0)
        n = SR * 4
        x = rng.normal(0, 1, n)
        y = rng.normal(0, 1, n)
        y *= np.sqrt(np.mean(x ** 2) / np.mean(y ** 2))  # equalize power
        mono = _integrated_lufs(x[np.newaxis, :], SR)
        stereo = _integrated_lufs(np.vstack([x, y]), SR)
        self.assertAlmostEqual(stereo - mono, 10 * np.log10(2), delta=0.2)

    def test_linearity_plus_6dB_per_factor_2(self):
        """Doubling amplitude raises loudness by 20*log10(2) ~= 6.02 dB."""
        x = sine(1000, 4.0, amp=0.3)
        l1 = _integrated_lufs(x[np.newaxis, :], SR)
        l2 = _integrated_lufs((2 * x)[np.newaxis, :], SR)
        self.assertAlmostEqual(l2 - l1, 20 * np.log10(2), delta=0.1)

    def test_gating_ignores_leading_silence(self):
        """Integrated loudness of [silence, tone] ~= loudness of [tone]."""
        loud = sine(1000, 3.0, amp=0.5)
        full = np.concatenate([np.zeros(SR * 3), loud])
        l_full = _integrated_lufs(full[np.newaxis, :], SR)
        l_loud = _integrated_lufs(loud[np.newaxis, :], SR)
        self.assertAlmostEqual(l_full, l_loud, delta=0.5)

    def test_fullscale_sine_in_plausible_range(self):
        """A 0 dBFS-peak 1 kHz sine should land in a sane LUFS range."""
        x = sine(1000, 4.0, amp=1.0)
        lufs = _integrated_lufs(x[np.newaxis, :], SR)
        # RMS -3.01 dBFS, K-weight ~ +2 dB at 1 kHz, -0.691 offset => ~ -1.7
        self.assertGreater(lufs, -4.0)
        self.assertLess(lufs, 0.0)


# ---------------------------------------------------------------------------
# Loudness Range (EBU Tech 3342)
# ---------------------------------------------------------------------------

class TestLoudnessRange(unittest.TestCase):
    def test_constant_level_lra_near_zero(self):
        x = sine(1000, 8.0, amp=0.5)
        lra = _loudness_range(x[np.newaxis, :], SR)
        self.assertLess(lra, 1.0)

    def test_two_level_signal_has_large_lra(self):
        quiet = sine(1000, 5.0, amp=0.05)
        loud = sine(1000, 5.0, amp=0.5)  # 20 dB louder
        full = np.concatenate([quiet, loud])
        lra = _loudness_range(full[np.newaxis, :], SR)
        self.assertGreater(lra, 10.0)


# ---------------------------------------------------------------------------
# True Peak
# ---------------------------------------------------------------------------

class TestTruePeak(unittest.TestCase):
    def test_sine_true_peak_matches_amplitude(self):
        """A sine of peak amplitude A has true peak ~= A (in dBTP)."""
        for amp in (0.5, 0.25):
            with self.subTest(amp=amp):
                x = sine(997, 1.0, amp=amp)  # non-bin frequency
                tp = _true_peak(x, SR)
                self.assertAlmostEqual(tp, 20 * np.log10(amp), delta=0.2)


# ---------------------------------------------------------------------------
# Authenticity regression (bundled test files)
# ---------------------------------------------------------------------------

class TestAuthenticityRegression(unittest.TestCase):
    def _report(self, name):
        path = TESTDATA / name
        if not path.exists():
            self.skipTest(f"missing test file: {name}")
        return analyze_authenticity(read_audio(path))

    def test_genuine_files_are_clean(self):
        for name in ("01_genuine_96k_24bit.wav",
                     "02_cd_44k_16bit.wav",
                     "07_genuine_192k_24bit.wav"):
            with self.subTest(name=name):
                self.assertEqual(self._report(name).verdict, "clean")

    def test_upsampled_files_are_suspicious(self):
        for name in ("03_upsampled_44k_to_96k_24bit.wav",
                     "06_extreme_upsampled_22k_to_192k.wav"):
            with self.subTest(name=name):
                self.assertEqual(self._report(name).verdict, "suspicious")

    def test_fake_24bit_is_detected(self):
        r = self._report("04_fake24bit_padded.wav")
        self.assertTrue(r.is_suspicious)
        self.assertFalse(r.low_bits_active)

    def test_mp3_cutoff_is_detected(self):
        r = self._report("05_mp3_sourced_cutoff.flac")
        self.assertTrue(r.is_suspicious)
        self.assertTrue(r.has_sharp_cutoff)


# ---------------------------------------------------------------------------
# Full-pipeline smoke test
# ---------------------------------------------------------------------------

class TestPipelineSmoke(unittest.TestCase):
    def test_all_modules_run_without_error(self):
        path = TESTDATA / "01_genuine_96k_24bit.wav"
        if not path.exists():
            self.skipTest("missing test file")
        a = read_audio(path)
        extract_metadata(a)
        analyze_quality(a)
        loud = analyze_loudness(a)
        dr = analyze_dynamic_range(a)
        analyze_authenticity(a)
        # sanity: loudness/DR are finite numbers
        self.assertTrue(np.isfinite(loud.integrated_lufs))
        self.assertTrue(np.isfinite(dr.dr_precise_avg_db))


if __name__ == "__main__":
    unittest.main(verbosity=2)
