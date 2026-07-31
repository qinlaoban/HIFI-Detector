"""DR14 Dynamic Range meter — TT / Pleasurize Music Foundation style.

Reference: http://www.dynamicrange.de/

Algorithm (per channel):
1. Split audio into 0.5 s non-overlapping blocks.
2. Compute the RMS of each block (linear).
3. overall_rms = RMS of the whole channel
   (== power-average of the per-block RMS values).
4. peak_rms = the loudest block's RMS (the peak short-term RMS).
   RMS over a 0.5 s block already averages out sample-level transients,
   so the maximum block RMS is robust against isolated clicks.
5. DR = 20·log10(peak_rms / overall_rms)  ==  peak_dB − overall_dB.
6. Official DR = round(mean of the per-channel DR values) → integer.

Why this differs from the previous implementation:
    The old code compared the *power-average of the loudest 20% of blocks*
    to the overall RMS. That statistic is mathematically bounded:

        DR_max = 20·log10(1 / sqrt(0.2)) ≈ 6.99 dB

    so it could never report more than ~7 dB regardless of content — while
    real DR14 values range from DR4 (heavily limited) to DR15+ (dynamic
    classical/acoustic). The correct definition compares the *peak* short-term
    RMS level to the average RMS level (a difference of dB levels), which is
    unbounded and matches the TT DR Meter's behaviour.
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

    # Underlying metrics (dBFS)
    overall_rms_per_channel: list[float]  # average RMS of whole channel
    peak_rms_per_channel: list[float]     # loudest short-term block RMS
    window_size_s: float
    n_windows: int

    # Boundary risk (for values near rounding thresholds)
    boundary_risk: bool
    boundary_note: str


WINDOW_SIZE = 0.5  # seconds per block (short-term RMS window)


def analyze_dynamic_range(audio: AudioData) -> DRReport:
    """Calculate DR14 dynamic range for the audio file.

    Processes each channel independently: DR is the difference between the
    peak short-term RMS level and the average RMS level of the whole channel.
    """
    samples = audio.samples  # (channels, n_samples)
    sample_rate = audio.sample_rate
    n_channels = audio.channels

    window_samples = int(WINDOW_SIZE * sample_rate)
    if window_samples < 1:
        window_samples = 1

    n_total = audio.n_samples
    n_windows = n_total // window_samples

    if n_windows < 2:
        return DRReport(
            dr_precise_db=[0.0] * n_channels,
            dr_precise_avg_db=0.0,
            dr_official=0,
            rating="N/A",
            rating_color="dim",
            overall_rms_per_channel=[float("-inf")] * n_channels,
            peak_rms_per_channel=[float("-inf")] * n_channels,
            window_size_s=WINDOW_SIZE,
            n_windows=n_windows,
            boundary_risk=False,
            boundary_note="Audio too short for DR measurement",
        )

    dr_values = []
    overall_rms_db = []
    peak_rms_db = []

    for ch in range(n_channels):
        metrics = _dr_for_channel(samples[ch], n_windows, window_samples)
        dr_values.append(metrics["dr_precise"])
        overall_rms_db.append(metrics["overall_rms_db"])
        peak_rms_db.append(metrics["peak_rms_db"])

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
        peak_rms_per_channel=[round(v, 2) for v in peak_rms_db],
        window_size_s=WINDOW_SIZE,
        n_windows=n_windows,
        boundary_risk=boundary_risk,
        boundary_note=boundary_note,
    )


def _dr_for_channel(
    channel: np.ndarray, n_windows: int, window_samples: int
) -> dict:
    """Compute DR14 for a single audio channel.

    DR = peak short-term RMS (dB) − overall RMS (dB).

    Args:
        channel: 1D audio samples (float64, [-1, 1])
        n_windows: total number of 0.5 s blocks
        window_samples: samples per block

    Returns:
        dict with dr_precise, overall_rms_db, peak_rms_db
    """
    truncated = channel[: n_windows * window_samples]
    windows = truncated.reshape(n_windows, window_samples)
    rms_values = np.sqrt(np.mean(windows ** 2, axis=1))

    # Overall RMS = RMS of the whole channel (power-average of block RMS).
    overall_avg = np.sqrt(np.mean(rms_values ** 2)) if np.any(rms_values > 0) else 1e-12

    # Peak RMS = the loudest short-term block.
    peak_avg = float(np.max(rms_values)) if rms_values.size else 1e-12
    if peak_avg <= 0:
        peak_avg = 1e-12

    if overall_avg > 0 and peak_avg > 0:
        dr_precise = float(20 * np.log10(peak_avg / overall_avg))
    else:
        dr_precise = 0.0

    # Report levels in dBFS.
    peak_db = float(20 * np.log10(peak_avg))
    overall_db = float(20 * np.log10(overall_avg))

    return {
        "dr_precise": dr_precise,
        "overall_rms_db": overall_db,
        "peak_rms_db": peak_db,
    }


def _rate_dr(dr_value: int) -> tuple[str, str]:
    """Rate a DR value per Pleasurize Music Foundation recommendations.

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

    If precise DR is very close to the rounding threshold (±0.5),
    the official DR integer may be off by 1.
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
