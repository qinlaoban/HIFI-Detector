"""Tests for the focused Hi-Res authenticity verdict (hires.py).

Covers:
  * Pure verdict logic (derive_verdict / claims_hires) — no audio needed.
  * Integration on the bundled test files (genuine / upsampled / fake24 /
    lossy-cutoff / CD).

Run: .venv/bin/python -m unittest discover -s tests -v
"""

import unittest
from pathlib import Path

from hifi_detector.core.audio_io import read_audio
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
