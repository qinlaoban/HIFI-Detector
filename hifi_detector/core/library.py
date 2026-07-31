"""Library scanning, album grading and the "loudness war" report.

This is the heart of the product repositioning: instead of forensically
asking "is this one file a fake?", we scan a whole music library and answer
the questions music lovers actually care about:

  * How good does my collection sound, overall?
  * Which albums got crushed by the loudness war?
  * I own several versions of an album — which one should I keep?

Design:
  * Pure logic (grading, album aggregation, library summary) is separated
    from file I/O so it can be unit-tested without touching disk.
  * Tracks are grouped into albums by their containing folder (the way most
    audiophile libraries are organised: Artist/Album/track.flac).
  * Per-track metrics reuse the existing analyzers (DR14, BS.1770 LUFS,
    true peak, clipping, authenticity).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .audio_io import read_audio
from .authenticity import analyze_authenticity
from .dynamic_range import analyze_dynamic_range
from .loudness import analyze_loudness
from .quality import analyze_quality

DEFAULT_EXTENSIONS = {
    ".flac", ".wav", ".aiff", ".aif", ".mp3",
    ".ogg", ".opus", ".m4a", ".alac", ".ape", ".wv",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TrackResult:
    """Per-track analysis result."""

    path: str
    rel_path: str
    album_key: str          # grouping key (relative parent folder)
    title: str              # file name without extension
    duration_s: float
    sample_rate: int
    bit_depth: int
    channels: int
    format: str

    dr: int                 # official DR (rounded)
    dr_precise: float
    integrated_lufs: float
    loudness_range_lu: float
    true_peak_dbtp: float
    has_clipping: bool

    authenticity_verdict: str
    authenticity_reasons: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class AlbumResult:
    """Aggregated album-level result."""

    name: str
    folder: str
    n_tracks: int
    dr_median: int
    dr_min: int
    dr_max: int
    lufs_median: float
    grade: str              # "A+" .. "E"
    grade_label: str        # short human label
    verdict: str            # one-line human conclusion
    loudness_war: bool      # True if dynamics look crushed
    tracks: list[TrackResult] = field(default_factory=list)


@dataclass
class LibraryReport:
    """Whole-library summary."""

    root: str
    n_files: int
    n_errors: int
    n_albums: int
    avg_dr: float
    pct_crushed: float                 # % of albums flagged loudness-war
    grade_distribution: dict[str, int]
    albums: list[AlbumResult]          # sorted by DR ascending (worst first)


# ---------------------------------------------------------------------------
# Pure logic: grading
# ---------------------------------------------------------------------------

# Loudness-war threshold: albums at or below this DR are flagged.
LOUDNESS_WAR_DR = 7


def grade_from_dr(dr: int) -> tuple[str, str, str, bool]:
    """Map an album DR to a grade, label, human verdict and loudness-war flag.

    The grade scale is aligned with audiophile conventions (DR14+ is the
    gold standard for dynamic, uncrushed mastering).

    Returns:
        (grade, grade_label, verdict, loudness_war)
    """
    if dr >= 14:
        return ("A+", "发烧级动态",
                "动态充沛，未经压缩的发烧级母带", False)
    if dr >= 12:
        return ("A", "动态优秀",
                "动态范围优秀，保留良好", False)
    if dr >= 10:
        return ("B", "动态良好",
                "动态良好，轻度压缩", False)
    if dr >= 8:
        return ("C", "动态一般",
                "动态一般，有明显压缩痕迹", False)
    if dr >= 6:
        return ("D", "动态较差",
                "动态偏窄，疑似响度战争压缩", True)
    return ("E", "响度战争重灾区",
            "动态被严重压扁，典型响度战争牺牲品", True)


# ---------------------------------------------------------------------------
# Pure logic: aggregation
# ---------------------------------------------------------------------------

def _median_int(values: list[int]) -> int:
    import numpy as np
    return int(round(float(np.median(values)))) if values else 0


def _median_float(values: list[float]) -> float:
    import numpy as np
    return float(np.median(values)) if values else 0.0


def aggregate_album(
    album_key: str, name: str, folder: str, tracks: list[TrackResult]
) -> AlbumResult:
    """Aggregate per-track results into a single album result.

    Album DR is the *median* of track DRs (robust against one odd track).
    """
    ok = [t for t in tracks if t.error is None]
    drs = [t.dr for t in ok]
    lufs = [t.integrated_lufs for t in ok]

    dr_median = _median_int(drs)
    grade, label, verdict, loudness_war = grade_from_dr(dr_median)

    return AlbumResult(
        name=name,
        folder=folder,
        n_tracks=len(ok),
        dr_median=dr_median,
        dr_min=min(drs) if drs else 0,
        dr_max=max(drs) if drs else 0,
        lufs_median=round(_median_float(lufs), 1),
        grade=grade,
        grade_label=label,
        verdict=verdict,
        loudness_war=loudness_war,
        tracks=tracks,
    )


def summarize_library(root: str, albums: list[AlbumResult], n_errors: int) -> LibraryReport:
    """Build the whole-library summary from aggregated albums."""
    import numpy as np

    scored = [a for a in albums if a.n_tracks > 0]
    avg_dr = float(np.mean([a.dr_median for a in scored])) if scored else 0.0
    crushed = [a for a in scored if a.loudness_war]
    pct_crushed = (len(crushed) / len(scored) * 100) if scored else 0.0

    dist: dict[str, int] = {}
    for a in scored:
        dist[a.grade] = dist.get(a.grade, 0) + 1

    # Worst first (loudness-war report ordering).
    albums_sorted = sorted(scored, key=lambda a: (a.dr_median, a.lufs_median))

    return LibraryReport(
        root=root,
        n_files=sum(a.n_tracks for a in scored) + n_errors,
        n_errors=n_errors,
        n_albums=len(scored),
        avg_dr=round(avg_dr, 1),
        pct_crushed=round(pct_crushed, 1),
        grade_distribution=dist,
        albums=albums_sorted,
    )


# ---------------------------------------------------------------------------
# I/O: scanning
# ---------------------------------------------------------------------------

def _analyze_one(path: Path, root: Path) -> TrackResult:
    """Analyze a single audio file into a TrackResult (error captured)."""
    rel = path.relative_to(root)
    album_key = str(rel.parent)
    title = path.stem

    base = dict(
        path=str(path),
        rel_path=str(rel),
        album_key=album_key,
        title=title,
    )

    try:
        audio = read_audio(path)
        dr = analyze_dynamic_range(audio)
        loud = analyze_loudness(audio)
        quality = analyze_quality(audio)
        auth = analyze_authenticity(audio)

        tp = loud.true_peak_db_l
        if loud.true_peak_db_r is not None:
            tp = max(tp, loud.true_peak_db_r)

        return TrackResult(
            **base,
            duration_s=round(audio.duration_s, 2),
            sample_rate=audio.sample_rate,
            bit_depth=audio.bit_depth,
            channels=audio.channels,
            format=audio.format,
            dr=dr.dr_official,
            dr_precise=dr.dr_precise_avg_db,
            integrated_lufs=loud.integrated_lufs,
            loudness_range_lu=loud.loudness_range_lu,
            true_peak_dbtp=round(tp, 2),
            has_clipping=quality.clip_samples > 0,
            authenticity_verdict=auth.verdict,
            authenticity_reasons=auth.suspicion_reasons,
        )
    except Exception as e:  # noqa: BLE001 — report, don't crash the scan
        return TrackResult(
            **base,
            duration_s=0.0, sample_rate=0, bit_depth=0, channels=0, format="",
            dr=0, dr_precise=0.0, integrated_lufs=0.0, loudness_range_lu=0.0,
            true_peak_dbtp=0.0, has_clipping=False,
            authenticity_verdict="error", authenticity_reasons=[],
            error=str(e),
        )


def iter_audio_files(
    root: Path, recursive: bool = True, extensions: Iterable[str] = DEFAULT_EXTENSIONS
) -> list[Path]:
    """List audio files under root."""
    exts = {e.lower() for e in extensions}
    pattern = "**/*" if recursive else "*"
    return sorted(
        p for p in root.glob(pattern)
        if p.is_file() and p.suffix.lower() in exts
    )


def scan_library(
    root: str | Path,
    recursive: bool = True,
    extensions: Iterable[str] = DEFAULT_EXTENSIONS,
    progress: Callable[[int, int, str], None] | None = None,
) -> LibraryReport:
    """Scan a music library and produce a graded, loudness-war-aware report.

    Args:
        root: library root directory.
        recursive: descend into subdirectories.
        extensions: audio file extensions to include.
        progress: optional callback(i, total, filename) for UI updates.

    Returns:
        LibraryReport with albums sorted worst-first.
    """
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {root_path}")

    files = iter_audio_files(root_path, recursive, extensions)
    total = len(files)

    # Analyze every track.
    results: list[TrackResult] = []
    for i, f in enumerate(files):
        if progress:
            progress(i + 1, total, f.name)
        results.append(_analyze_one(f, root_path))

    n_errors = sum(1 for r in results if r.error is not None)

    # Group into albums by folder.
    by_album: dict[str, list[TrackResult]] = {}
    for r in results:
        by_album.setdefault(r.album_key, []).append(r)

    albums: list[AlbumResult] = []
    for album_key, tracks in by_album.items():
        # Display name = innermost folder; fall back to root name for loose files.
        if album_key == ".":
            name = root_path.name
            folder = str(root_path)
        else:
            name = Path(album_key).name
            folder = str(root_path / album_key)
        albums.append(aggregate_album(album_key, name, folder, tracks))

    return summarize_library(str(root_path), albums, n_errors)
