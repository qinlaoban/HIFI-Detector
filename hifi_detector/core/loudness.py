"""Loudness analysis: RMS, True Peak (4x oversampling), Integrated LUFS.

References:
- ITU-R BS.1770-4 (LKFS/LUFS measurement)
- True Peak: ITU-R BS.1770 oversampling method
- EBU R128 (Loudness Range)
"""

from dataclasses import dataclass

import numpy as np
from scipy.signal import resample_poly, sosfilt

from .audio_io import AudioData


@dataclass
class LoudnessReport:
    """Loudness analysis results."""

    # RMS (per channel, in dBFS)
    rms_db_l: float
    rms_db_r: float | None

    # True Peak (per channel, in dBTP)
    true_peak_db_l: float
    true_peak_db_r: float | None

    # Integrated LUFS (whole file)
    integrated_lufs: float

    # Short-term loudness range
    loudness_range_lu: float


def analyze_loudness(audio: AudioData) -> LoudnessReport:
    """Calculate RMS, True Peak, and Integrated LUFS for the audio file."""
    samples = audio.samples
    sample_rate = audio.sample_rate

    # --- RMS ---
    rms_l = 20 * np.log10(np.sqrt(np.mean(samples[0] ** 2)) + 1e-12)
    rms_r = None
    if audio.channels >= 2:
        rms_r = 20 * np.log10(np.sqrt(np.mean(samples[1] ** 2)) + 1e-12)

    # --- True Peak (4x oversampling) ---
    tp_l = _true_peak(samples[0], sample_rate)
    tp_r = None
    if audio.channels >= 2:
        tp_r = _true_peak(samples[1], sample_rate)

    # --- K-weight filter (compute once, share) ---
    n_channels = samples.shape[0]
    if n_channels == 1:
        mono = samples[0]
    else:
        # BS.1770: downmix stereo to mono by averaging (not summing)
        mono = (samples[0] + samples[1]) / 2.0
    mono_kweighted = _k_weight_filter(mono, sample_rate)

    # --- Integrated LUFS ---
    il = _integrated_lufs(mono_kweighted, sample_rate)

    # --- Loudness Range ---
    lra = _loudness_range(mono_kweighted, sample_rate)

    return LoudnessReport(
        rms_db_l=round(float(rms_l), 2),
        rms_db_r=round(float(rms_r), 2) if rms_r is not None else None,
        true_peak_db_l=round(float(tp_l), 2),
        true_peak_db_r=round(float(tp_r), 2) if tp_r is not None else None,
        integrated_lufs=round(float(il), 1),
        loudness_range_lu=round(float(lra), 1),
    )


def _true_peak(channel: np.ndarray, sample_rate: int) -> float:
    """Calculate True Peak using 4x oversampling (ITU-R BS.1770).

    Uses a 12th-order polyphase lowpass filter.
    """
    # 4x upsampling using scipy's polyphase resampling
    upsampled = resample_poly(channel, 4, 1, padtype="line")

    # Find the absolute peak
    peak = np.max(np.abs(upsampled))

    if peak <= 0:
        return float("-inf")

    return float(20 * np.log10(peak))


def _integrated_lufs(mono_kweighted: np.ndarray, sample_rate: int) -> float:
    """Calculate Integrated LUFS using ITU-R BS.1770 K-weighting.

    Uses 400ms blocks with 75% overlap (step = 100ms) per BS.1770-4.
    Two-pass gating: absolute (-70 LUFS) then relative (-10 LU).
    """
    block_size = int(0.4 * sample_rate)
    step_size = int(0.1 * sample_rate)  # 75% overlap
    if block_size < 1 or step_size < 1:
        return -120.0

    n_samples = len(mono_kweighted)
    if n_samples < block_size:
        return -120.0

    # Compute mean power for each overlapping block (vectorized via stride tricks)
    n_blocks = (n_samples - block_size) // step_size + 1
    # Use sliding window view for efficiency
    from numpy.lib.stride_tricks import sliding_window_view
    windows = sliding_window_view(mono_kweighted, block_size)[::step_size]
    powers = np.mean(windows ** 2, axis=1)

    if np.all(powers <= 0):
        return -120.0

    # First pass: absolute gate at -70 LUFS
    gate_absolute = 10 ** ((-70 + 0.691) / 10)  # -70 LUFS in linear power
    gated_powers = powers[powers > gate_absolute]

    if len(gated_powers) == 0:
        return -70.0

    # Second pass: relative gate at -10 LU below mean of gated blocks
    relative_mean = np.mean(gated_powers)
    gate_relative = relative_mean * 10 ** (-10 / 10)
    gated_powers_2 = gated_powers[gated_powers > gate_relative]

    if len(gated_powers_2) == 0:
        final_power = relative_mean
    else:
        final_power = np.mean(gated_powers_2)

    # Convert to LUFS
    if final_power <= 0:
        return -120.0

    lufs = -0.691 + 10 * np.log10(final_power)
    return float(lufs)


def _loudness_range(mono_kweighted: np.ndarray, sample_rate: int) -> float:
    """Calculate Loudness Range (LRA) per EBU Tech 3342 / EBU R128.

    Algorithm (MathWorks reference implementation of EBU Tech 3342):
      1. 3-second blocks with 2.9s overlap (step = 0.1s)
      2. Compute short-term loudness (LUFS) for each block
      3. Absolute gate: remove blocks < -70 LUFS
      4. Convert gated loudness back to linear power, take mean
      5. Relative gate: -20 LU below that mean (in linear)
      6. LRA = 95th percentile - 10th percentile of surviving blocks
    """
    block_size = int(3.0 * sample_rate)
    step_size = max(1, int(0.1 * sample_rate))  # 96.7% overlap per EBU Tech 3342
    if block_size < 1 or step_size < 1:
        return 0.0

    n_samples = len(mono_kweighted)
    if n_samples < block_size:
        return 0.0

    n_blocks = (n_samples - block_size) // step_size + 1
    if n_blocks < 2:
        return 0.0

    # Vectorized block power computation with overlapping windows
    from numpy.lib.stride_tricks import sliding_window_view
    windows = sliding_window_view(mono_kweighted, block_size)[::step_size]
    powers = np.mean(windows ** 2, axis=1)

    # Short-term loudness in LUFS
    st_loudness = np.full(n_blocks, -120.0)
    mask = powers > 0
    st_loudness[mask] = -0.691 + 10 * np.log10(powers[mask])

    # Step 1: Absolute gate at -70 LUFS (per EBU Tech 3342)
    abs_gated = st_loudness[st_loudness >= -70.0]
    if len(abs_gated) < 2:
        return 0.0

    # Step 2: Convert abs-gated loudness back to linear power, take mean
    abs_gated_linear = 10 ** (abs_gated / 10.0)
    mean_linear = float(np.mean(abs_gated_linear))
    if mean_linear <= 0:
        return 0.0

    # Step 3: Relative gate at -20 LU below the abs-gated mean
    relative_threshold_lufs = -20.0 + 10 * np.log10(mean_linear)
    rel_gated = abs_gated[abs_gated >= relative_threshold_lufs]
    if len(rel_gated) < 2:
        return 0.0

    # Step 4: 10th and 95th percentiles
    sorted_l = np.sort(rel_gated)
    p10_idx = max(0, int(len(sorted_l) * 0.1))
    p95_idx = min(len(sorted_l) - 1, int(len(sorted_l) * 0.95))

    lra = float(sorted_l[p95_idx] - sorted_l[p10_idx])
    return lra


def _k_weight_filter(sig: np.ndarray, sample_rate: int) -> np.ndarray:
    """Apply ITU-R BS.1770 K-weighting filter to mono signal.

    Two cascaded biquad (second-order IIR) stages:
      Stage 1: High-shelf pre-filter (+4 dB above ~1500 Hz)
      Stage 2: RLB high-pass filter (fc ≈ 38.1 Hz, Q ≈ 0.5003)

    Coefficients derived via bilinear transform of the analog prototypes
    specified in ITU-R BS.1770-4.
    """
    sos = np.vstack([
        _high_shelf_biquad(sample_rate, gain_db=3.999843853973347, f0=1681.974450955533, Q=0.7071752369554196),
        _high_pass_biquad(sample_rate, f0=38.13547087602444, Q=0.5003270373238773),
    ])
    return sosfilt(sos, sig).astype(np.float64)


def _high_shelf_biquad(fs: int, gain_db: float, f0: float, Q: float) -> np.ndarray:
    """Design a high-shelf biquad filter (Audio EQ Cookbook formulas).

    Returns a single SOS section [b0, b1, b2, a0, a1, a2] (normalized).
    """
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / fs
    alpha = np.sin(w0) / (2.0 * Q)
    cos_w0 = np.cos(w0)
    sqrt_A = np.sqrt(A)

    b0 = A * ((A + 1) + (A - 1) * cos_w0 + 2 * sqrt_A * alpha)
    b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
    b2 = A * ((A + 1) + (A - 1) * cos_w0 - 2 * sqrt_A * alpha)
    a0 = (A + 1) - (A - 1) * cos_w0 + 2 * sqrt_A * alpha
    a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
    a2 = (A + 1) - (A - 1) * cos_w0 - 2 * sqrt_A * alpha

    return np.array([b0, b1, b2, a0, a1, a2]) / a0


def _high_pass_biquad(fs: int, f0: float, Q: float) -> np.ndarray:
    """Design a 2nd-order Butterworth high-pass biquad filter.

    Returns a single SOS section [b0, b1, b2, a0, a1, a2] (normalized).
    """
    w0 = 2 * np.pi * f0 / fs
    alpha = np.sin(w0) / (2.0 * Q)
    cos_w0 = np.cos(w0)

    b0 = (1 + cos_w0) / 2
    b1 = -(1 + cos_w0)
    b2 = (1 + cos_w0) / 2
    a0 = 1 + alpha
    a1 = -2 * cos_w0
    a2 = 1 - alpha

    return np.array([b0, b1, b2, a0, a1, a2]) / a0
