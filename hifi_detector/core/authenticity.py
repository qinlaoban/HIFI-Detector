"""Authenticity detection: lossy-to-lossless, upsampling, and bit-depth forgery.

This module answers the key question of the entire tool:
"Is this FLAC/WAV really what it claims to be?"

Detection algorithms:
  1. Spectral cutoff detection — find the unnatural frequency cap typical of
     lossy codecs (MP3 at 16/18/20 kHz, AAC at ~17 kHz).
  2. Upsampling detection — check if a high-sample-rate file actually contains
     information above the CD Nyquist frequency (22.05 kHz).
  3. Low-bit quantization check — verify the LSB is actually used (not all zeros),
     especially for 24-bit files that might be 16-bit in disguise.

All algorithms are non-destructive and operate in the frequency domain.
"""

from dataclasses import dataclass, field

import numpy as np
from scipy import signal
from scipy.fft import rfft, rfftfreq

from .audio_io import AudioData


# ---------------------------------------------------------------------------
# Known lossy codec cutoff frequencies (approximate, varies by encoder)
# ---------------------------------------------------------------------------
# These are the -3 dB cutoff points where the encoder's lowpass filter kicks in.
_CODEC_CUTOFFS = {
    "MP3 128kbps": (15500, 16500),
    "MP3 160kbps": (16500, 17500),
    "MP3 192kbps": (18000, 19500),
    "MP3 256kbps": (19500, 20500),
    "MP3 320kbps": (20000, 21000),
    "AAC 128kbps": (15500, 17000),
    "AAC 192kbps": (17000, 18500),
    "AAC 256kbps": (18500, 20000),
    "Opus 96kbps":  (18000, 20000),
    "Opus 128kbps": (19000, 20500),
}

# Frequency above which we check for "hi-res" content
CD_NYQUIST = 22050


@dataclass
class AuthenticityReport:
    """Authenticity analysis results."""

    # --- Spectral cutoff detection ---
    cutoff_freq_hz: float | None          # detected -6 dB cutoff frequency, or None
    cutoff_suspected_codec: str | None    # suspected lossy codec name, or None
    has_sharp_cutoff: bool                # True if a sharp spectral edge is detected
    cutoff_confidence: float              # 0.0 - 1.0 confidence in cutoff detection

    # --- Upsampling detection ---
    is_suspected_upsampled: bool
    hf_energy_ratio: float                # ratio of energy above 22.05 kHz to total
    hf_energy_db: float                   # energy above 22.05 kHz in dB relative to max
    upsample_source_rate_hint: int | None # hinted original sample rate (e.g. 44100)

    # --- Bit depth authenticity ---
    low_bits_active: bool                 # True if low 8 bits for 24-bit have variance
    fake_24bit_confidence: float          # 0.0-1.0 confidence it's fake 24-bit

    # --- Combined verdict ---
    is_suspicious: bool
    suspicion_reasons: list[str] = field(default_factory=list)
    overall_confidence: float = 0.0
    verdict: str = "clean"  # "clean" | "ambiguous" | "suspicious"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_authenticity(audio: AudioData) -> AuthenticityReport:
    """Run all authenticity checks on audio data.

    Args:
        audio: AudioData from audio_io.read_audio()

    Returns:
        AuthenticityReport with all detection results.
    """
    samples = audio.samples  # (channels, n_samples)
    sr = audio.sample_rate

    # --- 1. Spectral cutoff detection ---
    cutoff_freq, cutoff_codec, has_sharp, cutoff_conf = _detect_spectral_cutoff(
        samples, sr
    )

    # --- 2. Upsampling detection ---
    is_up, hf_ratio, hf_db, src_hint = _detect_upsampling(samples, sr)

    # --- 3. Fake 24-bit detection ---
    low_bits_ok, fake_24_conf = _detect_fake_24bit(samples, audio.bit_depth)

    # --- Combine ---
    reasons = []
    confidence = 0.0

    if has_sharp and cutoff_conf > 0.5:
        reasons.append(f"Spectral cutoff at ~{cutoff_freq / 1000:.1f} kHz, " +
                       f"suspected {cutoff_codec or 'lossy codec'}")
        confidence = max(confidence, cutoff_conf * 0.6)

    if is_up:
        reasons.append(
            f"High sample rate ({sr} Hz) but no content above {CD_NYQUIST / 1000:.0f} kHz, "
            f"likely upsampled from {src_hint} Hz"
        )
        confidence = max(confidence, 0.85)

    if not low_bits_ok:
        reasons.append(f"24-bit file appears to be padded from 16-bit")
        confidence = max(confidence, fake_24_conf * 0.5)

    is_suspicious = len(reasons) > 0

    # Three-tier verdict for the frontend
    if not is_suspicious:
        verdict = "clean"
    elif confidence < 0.6:
        verdict = "ambiguous"
    else:
        verdict = "suspicious"

    return AuthenticityReport(
        cutoff_freq_hz=round(cutoff_freq, 1) if cutoff_freq else None,
        cutoff_suspected_codec=cutoff_codec,
        has_sharp_cutoff=has_sharp,
        cutoff_confidence=round(cutoff_conf, 3),
        is_suspected_upsampled=is_up,
        hf_energy_ratio=round(hf_ratio, 6),
        hf_energy_db=round(hf_db, 1),
        upsample_source_rate_hint=src_hint,
        low_bits_active=low_bits_ok,
        fake_24bit_confidence=round(fake_24_conf, 3),
        is_suspicious=is_suspicious,
        suspicion_reasons=reasons,
        overall_confidence=round(confidence, 3),
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# 1. Spectral cutoff detection
# ---------------------------------------------------------------------------

def _detect_spectral_cutoff(
    samples: np.ndarray, sr: int
) -> tuple[float | None, str | None, bool, float]:
    """Detect unnatural spectral cutoff characteristic of lossy codecs.

    Approach (multi-frame, inspired by audiocheckr best practices):
      1. Sample N frames evenly spaced across the track to avoid being
         fooled by silent intros, fade-outs, or atypical passages.
      2. Compute Welch PSD on each frame, take the median spectrum.
      3. Compute gradient in dB/kHz — independent of FFT resolution.
      4. A codec cutoff shows as >120 dB/kHz drop in the 14–21 kHz range.
      5. Real audio has gradual roll-off; lossy codecs are surgical.

    Returns:
        (cutoff_freq_hz, codec_name, has_sharp_cutoff, confidence)
    """
    if sr < 32000:
        return None, None, False, 0.0

    n_total = samples.shape[1]
    n_per_seg = min(4096, n_total)
    if n_per_seg < 256:
        return None, None, False, 0.0

    # --- Multi-frame sampling: pick frames from the LOUDEST sections ---
    # Evenly-spaced sampling can miss content in dynamic audio.
    # Instead: scan short blocks, pick the N loudest ones.
    n_frames = 5
    frame_len = n_per_seg
    # Scan the track in frame_len blocks, compute RMS for each
    n_blocks = n_total // frame_len
    if n_blocks < 1:
        return None, None, False, 0.0
    block_rms = np.array([
        np.sqrt(np.mean(samples[0, i * frame_len:(i + 1) * frame_len] ** 2))
        for i in range(n_blocks)
    ])
    # Pick top N loudest blocks (ensures we analyze actual content)
    top_indices = np.argsort(block_rms)[::-1][:n_frames]
    frame_positions = sorted(int(i) * frame_len for i in top_indices)

    # Compute Welch PSD for each frame (use first channel for speed)
    all_psd = []
    for pos in frame_positions:
        frame = samples[0, pos: pos + frame_len]
        if len(frame) < n_per_seg:
            continue
        _, psd = signal.welch(
            frame, fs=sr, nperseg=n_per_seg,
            window="hann", noverlap=n_per_seg // 2,
            scaling="density"
        )
        all_psd.append(psd)

    if not all_psd:
        return None, None, False, 0.0

    # Average across channels: add second channel if stereo
    if samples.shape[0] > 1:
        all_psd_r = []
        for pos in frame_positions:
            frame = samples[1, pos: pos + frame_len]
            if len(frame) < n_per_seg:
                continue
            _, psd_r = signal.welch(
                frame, fs=sr, nperseg=n_per_seg,
                window="hann", noverlap=n_per_seg // 2,
                scaling="density"
            )
            all_psd_r.append(psd_r)
        if len(all_psd_r) == len(all_psd):
            all_psd = [(l + r) / 2 for l, r in zip(all_psd, all_psd_r)]

    # Take median PSD across frames (robust against outliers)
    psd_stack = np.array(all_psd)
    median_psd = np.median(psd_stack, axis=0)

    freqs = signal.welch(
        np.zeros(n_per_seg), fs=sr, nperseg=n_per_seg,
        window="hann", noverlap=n_per_seg // 2, scaling="density"
    )[0]

    mag_db = 10 * np.log10(median_psd + 1e-30)

    # Focus on 10-22 kHz (wider range to detect the plateau and slope)
    lo_idx = int(10000 * n_per_seg / sr)
    hi_idx = min(int(22000 * n_per_seg / sr), len(mag_db))

    if hi_idx - lo_idx < 20:
        return None, None, False, 0.0

    band_db = mag_db[lo_idx:hi_idx]
    band_freqs = freqs[lo_idx:hi_idx]

    # Light smoothing to suppress FFT ripple while keeping edges
    window = min(5, len(band_db) - 2)
    if window >= 3 and window % 2 == 0:
        window -= 1
    if window < 3:
        return None, None, False, 0.0

    smooth_db = signal.savgol_filter(band_db, window, 2)

    # Compute gradient, normalize to dB/kHz
    freq_bin_hz = float(sr / n_per_seg)
    gradient_db_per_bin = np.diff(smooth_db)
    gradient_db_per_khz = gradient_db_per_bin / (freq_bin_hz / 1000.0)

    if len(gradient_db_per_khz) == 0:
        return None, None, False, 0.0

    # Find steepest negative gradient
    min_idx = int(np.argmin(gradient_db_per_khz))
    steepest_drop = abs(float(gradient_db_per_khz[min_idx]))

    # Threshold: >120 dB/kHz is a sharp artificial cutoff
    # Codec lowpass filters produce >150 dB/kHz; natural roll-off <100 dB/kHz.
    # 120 dB/kHz ≈ 30 dB drop within 250 Hz transition band.
    has_sharp_cutoff = steepest_drop > 120.0

    if not has_sharp_cutoff:
        return None, None, False, 0.0

    cutoff_freq_hz = float(band_freqs[min_idx])

    # Validate cutoff is in the codec range (14-22 kHz)
    if cutoff_freq_hz < 14000:
        return None, None, False, 0.0

    # Compute plateau level relative to band peak (not absolute)
    # Welch PSD values vary with signal level; use relative comparison
    pre_idx = max(0, min_idx - 3)
    plateau_db = float(np.mean(smooth_db[max(5, pre_idx - 5):pre_idx + 1]))
    band_peak_db = float(np.max(smooth_db[:max(10, pre_idx)]))
    plateau_rel = plateau_db - band_peak_db  # relative to band peak

    # Plateau must be within 30 dB of band peak (real content, not noise floor)
    if plateau_rel < -30:
        return None, None, False, 0.0

    # Check what happens after the drop: energy should stay low
    post_region = smooth_db[min_idx:min_idx + min(20, len(smooth_db) - min_idx)]
    if len(post_region) > 5:
        post_db = float(np.mean(post_region[-5:]))
        # If the signal recovers after the drop, it's not a codec cutoff
        # Check: energy must stay below plateau - 5 dB (trends downward, never bounces back)
        if post_db > plateau_db - 5:
            return None, None, False, 0.0

    # Match to known codec
    codec_match = _match_cutoff_to_codec(cutoff_freq_hz)
    confidence = _cutoff_confidence(steepest_drop, cutoff_freq_hz, plateau_db, smooth_db)

    return cutoff_freq_hz, codec_match, True, confidence


def _match_cutoff_to_codec(cutoff_freq: float) -> str | None:
    """Match a detected cutoff to a known lossy codec profile."""
    best_codec = None
    best_dist = float("inf")

    for codec, (lo, hi) in _CODEC_CUTOFFS.items():
        if lo <= cutoff_freq <= hi:
            center = (lo + hi) / 2
            dist = abs(cutoff_freq - center)
            if dist < best_dist:
                best_dist = dist
                best_codec = codec

    return best_codec


def _cutoff_confidence(
    drop_db_per_khz: float,
    cutoff_freq: float,
    plateau_db: float,
    smooth_db: np.ndarray,
) -> float:
    """Compute confidence (0-1) that this is a real codec cutoff, not natural roll-off.

    Args:
        drop_db_per_khz: steepest gradient in dB/kHz
        cutoff_freq: detected cutoff frequency in Hz
        plateau_db: pre-cutoff plateau level in dB
        smooth_db: smoothed magnitude array for post-drop analysis

    Factors that increase confidence:
      - Very steep drop (>1000 dB/kHz → 1.0)
      - Cutoff in typical lossy range (15-21 kHz)
      - Drop sustained below plateau by >25 dB
    """
    conf = 0.0

    # 1. Steepness: 120 → 0.3, 400 → 0.7, 1500+ → 1.0
    steep_score = min(1.0, max(0.0, (drop_db_per_khz - 120) / 1380))
    conf += steep_score * 0.4

    # 2. Cutoff frequency in "sweet spot" for codecs (14-21 kHz)
    if 14000 <= cutoff_freq <= 21000:
        freq_score = 1.0 - abs(cutoff_freq - 17500) / 3500
        freq_score = max(0.0, min(1.0, freq_score))
    else:
        freq_score = 0.2
    conf += freq_score * 0.3

    # 3. Sustained drop: energy stays low after cutoff
    mid_point = len(smooth_db) // 2
    min_after = float(np.min(smooth_db[mid_point:]))
    if min_after < plateau_db - 25:
        drop_score = 1.0
    elif min_after < plateau_db - 15:
        drop_score = 0.7
    elif min_after < plateau_db - 10:
        drop_score = 0.4
    else:
        drop_score = 0.1
    conf += drop_score * 0.3

    return min(1.0, conf)


# ---------------------------------------------------------------------------
# 2. Upsampling detection
# ---------------------------------------------------------------------------

def _detect_upsampling(
    samples: np.ndarray, sr: int
) -> tuple[bool, float, float, int | None]:
    """Detect if a high-sample-rate file is upsampled from a lower rate.

    Key heuristics (revised to reduce false positives per audiocheckr findings):
      - If sr > 48 kHz, check if there is meaningful energy above 22.05 kHz.
      - Low HF energy ratio alone is NOT sufficient to flag upsampling.
        Genuine hi-res recordings (classical, acoustic) may have very little
        ultrasonic content. Require corroborating evidence:
          (a) A sharp brickwall cutoff near 22.05 kHz (CD Nyquist), OR
          (b) Extremely low energy (< 0.01%) combined with flat interpolation noise
      - Source rate hint considers both 44100 and 48000.

    Returns:
        (is_suspected, hf_energy_ratio, hf_energy_db, source_rate_hint)
    """
    if sr <= 48000:
        return False, 0.0, -999.0, None

    # --- Multi-frame FFT for robust spectral estimate ---
    n_total = samples.shape[1]
    n_frames = min(5, max(1, n_total // (sr * 2)))  # up to 5 x 2-second frames
    frame_len = min(n_total, sr * 2)
    frame_len = 2 ** int(np.log2(frame_len))

    # Pick frame positions evenly spaced (skip first/last 10%)
    margin = n_total // 10
    if n_total - 2 * margin < frame_len:
        frame_positions = [0]
    else:
        usable = n_total - 2 * margin - frame_len
        step = usable // max(1, n_frames - 1) if n_frames > 1 else 0
        frame_positions = [margin + i * step for i in range(n_frames)]

    all_mag_db = []
    freqs = rfftfreq(frame_len, 1 / sr)
    for pos in frame_positions:
        frame = samples[0, pos: pos + frame_len]
        if len(frame) < frame_len:
            continue
        spec = np.abs(rfft(frame))
        mag_db = 20 * np.log10(spec + 1e-12)
        all_mag_db.append(mag_db)

    if not all_mag_db:
        return False, 0.0, -999.0, None

    # Median magnitude across frames
    mag_db = np.median(np.array(all_mag_db), axis=0)

    # Energy above CD Nyquist (22.05 kHz)
    hf_mask = freqs > CD_NYQUIST
    if not np.any(hf_mask):
        return False, 0.0, -999.0, None

    # Total energy (sum of squared magnitudes, proportional to signal power)
    mag_linear = 10 ** (mag_db / 20)
    total_energy = float(np.sum(mag_linear ** 2))
    hf_energy = float(np.sum(mag_linear[hf_mask] ** 2))
    hf_ratio = hf_energy / total_energy if total_energy > 0 else 0.0

    # Max dB in HF region
    max_hf_db = float(np.max(mag_db[hf_mask])) if hf_energy > 0 else -999.0

    # --- Check for brickwall cutoff near CD Nyquist ---
    # This is the hallmark of a CD-sourced file upsampled to hi-res
    # Look for a sharp drop (>100 dB/kHz) in the 20-24 kHz region
    has_brickwall_at_cd = False
    lo_idx = int(20000 * frame_len / sr)
    hi_idx = min(int(24000 * frame_len / sr), len(mag_db))
    if hi_idx - lo_idx > 5:
        band_db = mag_db[lo_idx:hi_idx]
        # Smooth lightly
        win = min(5, len(band_db) - 2)
        if win >= 3 and win % 2 == 0:
            win -= 1
        if win >= 3:
            smooth = signal.savgol_filter(band_db, win, 2)
            freq_bin_hz = float(sr / frame_len)
            gradient = np.diff(smooth) / (freq_bin_hz / 1000.0)
            if len(gradient) > 0:
                steepest = abs(float(np.min(gradient)))
                if steepest > 100:  # sharp brickwall near CD Nyquist
                    has_brickwall_at_cd = True

    # --- Noise floor slope in ultrasonic band ---
    hf_indices = np.where(hf_mask)[0]
    slope = 0.0
    if len(hf_indices) > 10:
        hf_mags = mag_linear[hf_indices]
        hf_freqs = freqs[hf_indices]
        valid = hf_mags > 1e-12
        if np.sum(valid) >= 5:
            x = np.log10(hf_freqs[valid])
            y = np.log10(hf_mags[valid])
            slope, _ = np.polyfit(x, y, 1)

    # --- Combine heuristics (more conservative to reduce false positives) ---
    is_up = False
    src_hint = _guess_source_rate(sr)

    if has_brickwall_at_cd:
        # Strong evidence: brickwall at CD Nyquist + low HF energy
        if hf_ratio < 0.005:  # < 0.5% energy above 22.05 kHz
            is_up = True
            # Brickwall at CD Nyquist strongly implies 44100 Hz source
            src_hint = 44100
    elif hf_ratio < 0.0001:  # < 0.01% — extremely low, almost certainly upsampled
        # Require very flat interpolation noise (slope near 0 or very negative)
        if abs(slope) > 2.0 or slope > -0.5:
            is_up = True
    elif hf_ratio < 0.001 and slope < -3.0:
        # Low energy + rapid decay in ultrasonic band
        is_up = True

    if not is_up:
        src_hint = None

    return is_up, hf_ratio, max_hf_db, src_hint


def _guess_source_rate(sr: int) -> int | None:
    """Guess the most likely source sample rate for an upsampled file.

    Considers both 44100 and 48000 base rates.
    """
    if sr == 176400 or sr == 88200:
        return 44100
    elif sr == 192000 or sr == 96000:
        # 96kHz could be from 48kHz or 44.1kHz — prefer 44100 as it's
        # the more common CD-derived upsample source
        return 44100 if sr % 44100 == 0 else 48000
    else:
        for candidate in (44100, 48000):
            if sr % candidate == 0:
                return candidate
    return 48000


# ---------------------------------------------------------------------------
# 3. Fake 24-bit detection (enhanced)
# ---------------------------------------------------------------------------

def _detect_fake_24bit(
    samples: np.ndarray, bit_depth: int
) -> tuple[bool, float]:
    """Enhanced fake 24-bit detection using quantization histogram analysis.

    Beyond the simple LSB check in quality.py, this examines:
      - The distribution of sample values modulo the 16-bit LSB.
      - If all samples align perfectly to a 16-bit grid, it's fake.
      - Uses statistical threshold to handle dithering, which adds noise to
        mask the quantization, but still shows as a non-uniform LSB distribution.

    Returns:
        (low_bits_active, confidence_fake)
    """
    if bit_depth != 24:
        return True, 0.0

    lsb_16 = 1.0 / (2 ** 15)   # 16-bit LSB in [-1,1] float domain
    lsb_24 = 1.0 / (2 ** 23)   # 24-bit LSB

    # Flatten all channels
    flat = samples.flatten()

    if len(flat) < 1000:
        return True, 0.0

    # Method 1: 16-bit quantization residual (from quality.py, replicated for clarity)
    quantized_16 = np.round(flat / lsb_16) * lsb_16
    residual = flat - quantized_16
    residual_power = float(np.mean(residual ** 2))
    signal_power = float(np.mean(flat ** 2))

    if signal_power == 0:
        return True, 0.0

    residual_ratio = residual_power / signal_power

    # Method 2: Check the distribution of sample values modulo the 16-bit grid
    # Sub-sample 100k points for performance
    n_check = min(len(flat), 100_000)
    indices = np.random.default_rng(42).choice(len(flat), n_check, replace=False)
    subset = flat[indices]

    # What proportion of samples land on a 16-bit grid point?
    dist_to_16bit = np.abs(subset - np.round(subset / lsb_16) * lsb_16)
    on_16bit_grid = np.sum(dist_to_16bit < lsb_24 * 0.5)
    grid_ratio = float(on_16bit_grid) / n_check

    # Method 3: Standard deviation of the LSB-8 bits
    # If 24-bit is real, the low 8 bits should have reasonable entropy
    # Map to 24-bit integer domain
    int_24 = np.round(subset / lsb_24).astype(np.int64)
    low_8 = int_24 & 0xFF  # lowest 8 bits
    # Count unique values in low 8 bits
    unique_low8 = len(np.unique(low_8))

    # Combine methods into confidence
    conf = 0.0

    # Criterion 1: near-zero residual
    if residual_ratio < 1e-14:
        conf = max(conf, 0.95)
    elif residual_ratio < 1e-12:
        conf = max(conf, 0.85)
    elif residual_ratio < 1e-10:
        conf = max(conf, 0.60)

    # Criterion 2: grid alignment
    if grid_ratio > 0.99:
        conf = max(conf, 0.90)
    elif grid_ratio > 0.95:
        conf = max(conf, 0.70)
    elif grid_ratio > 0.80:
        conf = max(conf, 0.40)

    # Criterion 3: low-8-bit entropy (real 24-bit should use most of 256 values)
    if unique_low8 < 16:
        conf = max(conf, 0.85)
    elif unique_low8 < 64:
        conf = max(conf, 0.50)
    elif unique_low8 < 128:
        conf = max(conf, 0.30)

    # Normalize and clamp
    conf = min(1.0, conf)

    low_bits_active = conf < 0.60  # conservative: only flag if high confidence
    return low_bits_active, conf
