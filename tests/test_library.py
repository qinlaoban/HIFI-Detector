"""Unit tests for library scanning pure logic (grading / aggregation / summary).

These test the product logic without touching disk. Run with:
    .venv/bin/python -m unittest discover -s tests -v
"""

import unittest

from hifi_detector.core.library import (
    TrackResult,
    aggregate_album,
    grade_from_dr,
    summarize_library,
)


def track(dr: int, lufs: float = -14.0, album_key: str = "album", error=None) -> TrackResult:
    """Build a minimal TrackResult for aggregation tests."""
    return TrackResult(
        path=f"/lib/{album_key}/t.flac",
        rel_path=f"{album_key}/t.flac",
        album_key=album_key,
        title="t",
        duration_s=200.0,
        sample_rate=44100,
        bit_depth=16,
        channels=2,
        format="FLAC",
        dr=dr,
        dr_precise=float(dr),
        integrated_lufs=lufs,
        loudness_range_lu=8.0,
        true_peak_dbtp=-1.0,
        has_clipping=False,
        authenticity_verdict="clean",
        authenticity_reasons=[],
        error=error,
    )


class TestGrading(unittest.TestCase):
    def test_grade_boundaries(self):
        cases = {
            16: "A+", 14: "A+", 13: "A", 12: "A",
            11: "B", 10: "B", 9: "C", 8: "C",
            7: "D", 6: "D", 5: "E", 3: "E",
        }
        for dr, expected_grade in cases.items():
            with self.subTest(dr=dr):
                grade, _, _, _ = grade_from_dr(dr)
                self.assertEqual(grade, expected_grade)

    def test_loudness_war_flag(self):
        # DR <= 7 flagged as loudness-war; DR >= 8 not.
        for dr in (3, 5, 6, 7):
            self.assertTrue(grade_from_dr(dr)[3], f"DR{dr} should be flagged")
        for dr in (8, 10, 12, 15):
            self.assertFalse(grade_from_dr(dr)[3], f"DR{dr} should not be flagged")

    def test_verdict_is_human_readable(self):
        for dr in (3, 7, 9, 12, 15):
            _, label, verdict, _ = grade_from_dr(dr)
            self.assertTrue(label)
            self.assertTrue(verdict)


class TestAggregation(unittest.TestCase):
    def test_album_dr_is_median(self):
        tracks = [track(dr) for dr in (4, 5, 6, 14, 15)]  # median = 6
        album = aggregate_album("k", "Album", "/lib/Album", tracks)
        self.assertEqual(album.dr_median, 6)
        self.assertEqual(album.dr_min, 4)
        self.assertEqual(album.dr_max, 15)
        self.assertEqual(album.grade, "D")
        self.assertTrue(album.loudness_war)

    def test_errors_excluded_from_aggregation(self):
        tracks = [track(12), track(12), track(0, error="decode failed")]
        album = aggregate_album("k", "Album", "/lib/Album", tracks)
        self.assertEqual(album.n_tracks, 2)  # errored track not counted
        self.assertEqual(album.dr_median, 12)

    def test_dynamic_album_not_flagged(self):
        tracks = [track(dr) for dr in (13, 14, 14, 15)]
        album = aggregate_album("k", "Album", "/lib/Album", tracks)
        self.assertIn(album.grade, ("A+", "A"))
        self.assertFalse(album.loudness_war)


class TestLibrarySummary(unittest.TestCase):
    def _albums(self):
        a1 = aggregate_album("a", "Crushed", "/lib/a", [track(4), track(5), track(6)])
        a2 = aggregate_album("b", "Dynamic", "/lib/b", [track(14), track(14), track(15)])
        a3 = aggregate_album("c", "Mid", "/lib/c", [track(9), track(10), track(11)])
        return [a1, a2, a3]

    def test_avg_dr_and_distribution(self):
        report = summarize_library("/lib", self._albums(), n_errors=0)
        self.assertEqual(report.n_albums, 3)
        # album medians: Crushed=5, Dynamic=14, Mid=10 -> avg = 29/3 = 9.67
        self.assertAlmostEqual(report.avg_dr, round((5 + 14 + 10) / 3, 1), delta=0.05)
        self.assertEqual(report.grade_distribution.get("E"), 1)  # Crushed (DR5)
        self.assertEqual(report.grade_distribution.get("A+"), 1)  # Dynamic (DR14)

    def test_pct_crushed(self):
        report = summarize_library("/lib", self._albums(), n_errors=0)
        # 1 of 3 albums is loudness-war (DR<=7)
        self.assertAlmostEqual(report.pct_crushed, round(1 / 3 * 100, 1), delta=0.05)

    def test_sorted_worst_first(self):
        report = summarize_library("/lib", self._albums(), n_errors=0)
        drs = [a.dr_median for a in report.albums]
        self.assertEqual(drs, sorted(drs))  # ascending => worst first
        self.assertEqual(report.albums[0].name, "Crushed")

    def test_errors_counted(self):
        report = summarize_library("/lib", self._albums(), n_errors=2)
        self.assertEqual(report.n_errors, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
