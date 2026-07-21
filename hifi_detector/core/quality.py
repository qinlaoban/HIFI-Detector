"""Basic quality metrics: clipping, DC offset, channel balance, bit-depth verification."""

from dataclasses import dataclass

import numpy as np

from .audio_io import AudioData


@dataclass
class QualityReport:
    """Quality analysis results."""

    # Clipping
    clip_samples: int
    clip_ratio_pct: float
    max_sample: float
    min_sample: float

    # DC offset
    dc_offset_channel: list[float]
    dc_offset_pct: float  # max across all channels, as % of full scale

    # Channel balance
    rms_per_channel: list[float]
    balance_diff_db: float  # max L-R difference in dB

    # Bit depth verification
    effective_bits: int  # estimated true bit depth from LSB analysis
    bit_depth_suspicious: bool

    # Sample value distribution
    sample_count: int


def analyze_quality(audio: AudioData) -> QualityReport:
    """Run all quality checks on audio data."""
    samples = audio.samples  # (channels, n_samples)

    # --- Clipping detection ---
    # A sample at exactly ±1.0 is a clip
    clip_mask = np.abs(samples) >= 0.99999
    clip_samples = int(np.sum(clip_mask))
    total_samples = audio.n_samples * audio.channels
    clip_ratio = (clip_samples / total_samples * 100) if total_samples > 0 else 0.0
    max_val = float(np.max(samples))
    min_val = float(np.min(samples))

    # --- DC offset ---
    dc_per_channel = []
    for ch in range(audio.channels):
        dc = float(np.mean(samples[ch]))
        dc_per_channel.append(dc)
    dc_max_pct = max(abs(dc) for dc in dc_per_channel) * 100

    # --- Channel balance ---
    rms_per_channel = []
    for ch in range(audio.channels):
        rms = float(np.sqrt(np.mean(samples[ch] ** 2)))
        rms_per_channel.append(rms)

    balance_diff = 0.0
    if audio.channels == 2 and rms_per_channel[0] > 0 and rms_per_channel[1] > 0:
        # L/R difference in dB
        balance_diff = abs(
            20 * np.log10(rms_per_channel[0] / rms_per_channel[1])
        )

    # --- Effective bit depth ---
    effective_bits, bit_suspicious = _estimate_effective_bits(samples, audio.bit_depth)

    return QualityReport(
        clip_samples=clip_samples,
        clip_ratio_pct=round(clip_ratio, 4),
        max_sample=round(max_val, 6),
        min_sample=round(min_val, 6),
        dc_offset_channel=[round(dc, 6) for dc in dc_per_channel],
        dc_offset_pct=round(dc_max_pct, 4),
        rms_per_channel=[round(rms_db(rms_val), 2) if rms_val > 0 else float("-inf") for rms_val in rms_per_channel],
        balance_diff_db=round(balance_diff, 2),
        effective_bits=effective_bits,
        bit_depth_suspicious=bit_suspicious,
        sample_count=audio.n_samples,
    )


def _estimate_effective_bits(samples: np.ndarray, reported_bits: int) -> tuple[int, bool]:
    """Estimate the true bit depth by analyzing sample value granularity.

    Returns (effective_bits, is_suspicious).
    """
    if reported_bits != 24:
        return reported_bits, False

    # For 24-bit files, check if the low 8 bits are used or zero-padded.
    # Multiply 24-bit integer values by 2^8 to map to 32-bit range for analysis.
    # In float64 [-1,1] range, 24-bit LSB = 1 / 2^23
    lsb_24 = 1.0 / (2 ** 23)
    lsb_16 = 1.0 / (2 ** 15)

    # Quantize to 16-bit grid
    quantized_16 = np.round(samples / lsb_16) * lsb_16

    # Residual = difference between original and 16-bit quantized
    residual = samples - quantized_16

    # If residual is all zeros (within tolerance), it's really 16-bit
    residual_power = np.mean(residual ** 2)
    signal_power = np.mean(samples ** 2)

    if signal_power == 0:
        return reported_bits, False

    residual_ratio = residual_power / signal_power

    # If residual is negligible (< 1e-12), samples map perfectly to a 16-bit grid
    if residual_ratio < 1e-12:
        return 16, True

    return reported_bits, False


def rms_db(rms_val: float) -> float:
    """Convert RMS value (0-1 range) to dBFS."""
    if rms_val <= 0:
        return float("-inf")
    return 20 * np.log10(rms_val)
