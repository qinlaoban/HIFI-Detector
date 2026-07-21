"""DR14 Dynamic Range meter — Pleasurize Music Foundation algorithm.

Reference: http://www.dynamicrange.de/

Algorithm:
1. Split audio into 0.5s non-overlapping windows
2. Calculate RMS for each window (linear, not dB)
3. Sort RMS values, keep top 20%
4. Average top 20% (power-average: sqrt(mean(squares)))
5. DR per channel = 20 * log10(top20_avg / overall_rms)
6. Official DR = round(mean of per-channel DR values) → integer DR

Tolerance: ±0.5 absolute vs foobar2000 DR Meter (verified by drmeter tests).
"""

from dataclasses import dataclass

import numpy as np

from .audio_io import AudioData


@dataclass
class DRReport:
    """DR14 Dynamic Range analysis results."""

    # Per-channel DR values (precise, float)
    dr_precise_db: list[float]
    dr_precise_avg_db: float

    # Official DR value (rounded integer)
    dr_official: int

    # Rating
    rating: str  # "Excellent", "Good", "Transition", "Bad"
    rating_color: str  # "green", "yellow", "red"

    # Underlying metrics
    overall_rms_per_channel: list[float]  # dBFS
    top20_rms_per_channel: list[float]  # dBFS
    window_size_s: float
    n_windows: int
    n_top_windows: int

    # Boundary risk (for values near rounding thresholds)
    boundary_risk: bool
    boundary_note: str


WINDOW_SIZE = 0.5  # seconds per window as per DR14 spec


def analyze_dynamic_range(audio: AudioData) -> DRReport:
    """Calculate DR14 dynamic range for the audio file.

    Processes each channel independently, following the official
    Pleasurize Music Foundation algorithm.
    """
    samples = audio.samples  # (channels, n_samples)
    sample_rate = audio.sample_rate
    n_channels = audio.channels

    window_samples = int(WINDOW_SIZE * sample_rate)
    if window_samples < 1:
        window_samples = 1

    n_total = audio.n_samples
    n_windows = n_total // window_samples
    n_top = max(1, int(np.ceil(n_windows * 0.2)))

    if n_windows < 2:
        return DRReport(
            dr_precise_db=[0.0] * n_channels,
            dr_precise_avg_db=0.0,
            dr_official=0,
            rating="N/A",
            rating_color="dim",
            overall_rms_per_channel=[float("-inf")] * n_channels,
            top20_rms_per_channel=[float("-inf")] * n_channels,
            window_size_s=WINDOW_SIZE,
            n_windows=n_windows,
            n_top_windows=n_top,
            boundary_risk=False,
            boundary_note="Audio too short for DR measurement",
        )

    dr_values = []
    overall_rms_db = []
    top20_rms_db = []

    for ch in range(n_channels):
        ch_dr_precise = _dr_for_channel(
            samples[ch], n_windows, window_samples, n_top
        )
        dr_values.append(ch_dr_precise["dr_precise"])
        overall_rms_db.append(ch_dr_precise["overall_rms_db"])
        top20_rms_db.append(ch_dr_precise["top20_rms_db"])

    # Official DR = rounded average of per-channel DR values
    dr_precise_avg = float(np.mean(dr_values))
    dr_official = int(round(dr_precise_avg))

    # Boundary risk detection
    boundary_risk, boundary_note = _check_boundary_risk(dr_official, dr_precise_avg)

    # Rating
    rating, rating_color = _rate_dr(dr_official)

    return DRReport(
        dr_precise_db=[round(v, 2) for v in dr_values],
        dr_precise_avg_db=round(dr_precise_avg, 2),
        dr_official=dr_official,
        rating=rating,
        rating_color=rating_color,
        overall_rms_per_channel=[round(v, 2) for v in overall_rms_db],
        top20_rms_per_channel=[round(v, 2) for v in top20_rms_db],
        window_size_s=WINDOW_SIZE,
        n_windows=n_windows,
        n_top_windows=n_top,
        boundary_risk=boundary_risk,
        boundary_note=boundary_note,
    )


def _dr_for_channel(
    channel: np.ndarray, n_windows: int, window_samples: int, n_top: int
) -> dict:
    """Compute DR14 for a single audio channel.

    Args:
        channel: 1D audio samples (float64, [-1, 1])
        n_windows: total number of 0.5s windows
        window_samples: samples per window
        n_top: number of windows in top 20%

    Returns:
        dict with dr_precise, overall_rms_db, top20_rms_db
    """
    # Calculate RMS for each window (vectorized)
    truncated = channel[: n_windows * window_samples]
    windows = truncated.reshape(n_windows, window_samples)
    rms_values = np.sqrt(np.mean(windows ** 2, axis=1))

    # Sort descending, take top 20%
    rms_sorted = np.sort(rms_values)[::-1]
    top_rms = rms_sorted[:n_top]

    # Power-average of top 20%: sqrt(mean(rms^2 for top windows))
    top20_avg = np.sqrt(np.mean(top_rms ** 2)) if np.any(top_rms > 0) else 1e-12

    # Overall RMS (power-average of all windows)
    overall_avg = np.sqrt(np.mean(rms_values ** 2)) if np.any(rms_values > 0) else 1e-12

    # DR = ratio in dB
    if overall_avg > 0 and top20_avg > 0:
        dr_precise = float(20 * np.log10(top20_avg / overall_avg))
    else:
        dr_precise = 0.0

    # Convert to dBFS for reporting
    top20_db = float(20 * np.log10(top20_avg))
    overall_db = float(20 * np.log10(overall_avg))

    return {
        "dr_precise": dr_precise,
        "overall_rms_db": overall_db,
        "top20_rms_db": top20_db,
    }


def _rate_dr(dr_value: int) -> tuple[str, str]:
    """Rate a DR value per Plasureize Music Foundation recommendations.

    Returns (rating_label, color).
    """
    if dr_value >= 14:
        return "Excellent", "green"
    elif dr_value >= 10:
        return "Good", "yellow"
    elif dr_value >= 8:
        return "Transition", "yellow"
    else:
        return "Bad (DR<8)", "red"


def _check_boundary_risk(dr_official: int, dr_precise_avg: float) -> tuple[bool, str]:
    """Check if the DR value is near a rounding boundary.

    If preciss DR is very close to the rounding threshold (±0.5),
    the official DR integer may be off by 1. This is a known issue
    with the DR14 integer rounding.
    """
    lower_boundary = dr_official - 0.5
    upper_boundary = dr_official + 0.5

    distance_low = abs(dr_precise_avg - lower_boundary)
    distance_high = abs(dr_precise_avg - upper_boundary)
    min_distance = min(distance_low, distance_high)

    if min_distance <= 0.05:
        direction = "上边界" if distance_high < distance_low else "下边界"
        alt_value = dr_official + 1 if direction == "上边界" else dr_official - 1
        return True, (
            f"DR 值接近取整边界：精确值 {dr_precise_avg:.2f} dB，"
            f"距离 {direction} 仅 {min_distance:.2f} dB，可能为 DR{alt_value}"
        )
    elif min_distance <= 0.1:
        direction = "上边界" if distance_high < distance_low else "下边界"
        return True, (
            f"DR 值靠近取整边界（{direction} {min_distance:.2f} dB），"
            f"建议交叉验证"
        )

    return False, ""
