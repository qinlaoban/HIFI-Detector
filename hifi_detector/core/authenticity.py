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
class UpsamplingResult:
    """Structured result of the upsampling detector.

    ``strength`` separates strong evidence (brickwall at CD Nyquist, or
    extremely flat interpolation noise) from weak evidence (ultrasonic band
    suspicious but ambiguous), so the caller can downgrade weak hits to a
    "suspicious" verdict instead of an outright "fake".
    """

    is_suspected: bool = False
    strength: str = "none"                # "none" | "weak" | "strong"
    hf_energy_ratio: float = 0.0
    hf_energy_db: float = -999.0          # max dBFS above 22.05 kHz (absolute)
    ultrasonic_slope: float = 0.0
    hf_frame_consistency: float = 1.0     # 1 = identical across frames
    source_rate_hint: int | None = None


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
    upsample_strength: str                # "none" | "weak" | "strong"（判据强度）
    hf_energy_ratio: float                # ratio of energy above 22.05 kHz to total
    hf_energy_db: float                   # max dBFS above 22.05 kHz (absolute)
    ultrasonic_slope: float               # log-log slope of the ultrasonic band (natural decay < 0)
    hf_frame_consistency: float           # 0-1, higher = HF energy identical across frames
    natural_ultrasonic: bool              # positive evidence: real ultrasonic content/dynamics
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
    up = _detect_upsampling(samples, sr)

    # --- 3. Fake 24-bit detection ---
    low_bits_ok, fake_24_conf = _detect_fake_24bit(samples, audio.bit_depth)

    # --- Combine ---
    reasons = []
    confidence = 0.0

    if has_sharp and cutoff_conf > 0.5:
        reasons.append(f"Spectral cutoff at ~{cutoff_freq / 1000:.1f} kHz, " +
                       f"suspected {cutoff_codec or 'lossy codec'}")
        confidence = max(confidence, cutoff_conf * 0.6)

    if up.is_suspected:
        reasons.append(
            f"High sample rate ({sr} Hz) but no content above {CD_NYQUIST / 1000:.0f} kHz, "
            f"likely upsampled from {up.source_rate_hint} Hz"
        )
        confidence = max(confidence, 0.85 if up.strength == "strong" else 0.6)

    if not low_bits_ok:
        reasons.append(f"24-bit file appears to be padded from 16-bit")
        confidence = max(confidence, fake_24_conf * 0.5)

    is_suspicious = len(reasons) > 0

    # Positive evidence: the file actually contains real ultrasonic content
    # or dynamic ultrasonic noise (hallmark of a genuine hi-res recording),
    # not the flat interpolation residue of an upsampled file.
    natural_ultrasonic = bool(
        (up.hf_energy_db > -90 and up.hf_energy_ratio >= 0.001)
        or (up.hf_energy_db > -100 and up.hf_frame_consistency < 0.6)
    )

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
        is_suspected_upsampled=up.is_suspected,
        upsample_strength=up.strength,
        hf_energy_ratio=round(up.hf_energy_ratio, 6),
        hf_energy_db=round(up.hf_energy_db, 1),
        ultrasonic_slope=round(up.ultrasonic_slope, 3),
        hf_frame_consistency=round(up.hf_frame_consistency, 3),
        natural_ultrasonic=natural_ultrasonic,
        upsample_source_rate_hint=up.source_rate_hint,
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
) -> UpsamplingResult:
    """Detect if a high-sample-rate file is upsampled from a lower rate.

    Key heuristics (revised to reduce false positives per audiocheckr findings):
      - If sr > 48 kHz, check if there is meaningful energy above 22.05 kHz.
      - Low HF energy ratio alone is NOT sufficient to flag upsampling.
        Genuine hi-res recordings (classical, acoustic) may have very little
        ultrasonic content. Require corroborating evidence:
          (a) A sharp brickwall cutoff near 22.05 kHz (CD Nyquist), OR
          (b) Extremely low energy (< 0.01%) combined with flat interpolation noise
      - Ambiguous cases are downgraded to ``strength="weak"`` so the caller
        reports them as "suspicious" rather than "fake".

    Returns:
        UpsamplingResult with detection flag, strength and diagnostic features.
    """
    if sr <= 48000:
        return UpsamplingResult()

    # --- Multi-frame FFT on the LOUDEST sections ---
    # Evenly-spaced frames can land in silent intros / fade-outs and end up
    # measuring the noise floor instead of the signal (which makes hf_ratio
    # degenerate into "fraction of bins above 22 kHz"). Pick the loudest blocks
    # so the spectrum reflects real content — same strategy as the cutoff detector.
    n_total = samples.shape[1]
    frame_len = min(n_total, sr * 2)
    frame_len = 2 ** int(np.log2(frame_len))
    n_blocks = n_total // frame_len
    if n_blocks < 1:
        return UpsamplingResult()

    n_frames = min(5, n_blocks)
    block_rms = np.array([
        np.sqrt(np.mean(samples[0, i * frame_len:(i + 1) * frame_len] ** 2))
        for i in range(n_blocks)
    ])
    top = np.argsort(block_rms)[::-1][:n_frames]
    frame_positions = sorted(int(i) * frame_len for i in top)

    all_mag_db = []
    freqs = rfftfreq(frame_len, 1 / sr)
    hf_mask = freqs > CD_NYQUIST
    for pos in frame_positions:
        frame = samples[0, pos: pos + frame_len]
        if len(frame) < frame_len:
            continue
        spec = np.abs(rfft(frame))
        mag_db = 20 * np.log10(spec + 1e-12)
        all_mag_db.append(mag_db)

    if not all_mag_db:
        return UpsamplingResult()
    if not np.any(hf_mask):
        return UpsamplingResult()

    # Per-frame HF energy ratio (for frame-to-frame consistency).
    per_frame_ratio = []
    for mag_db in all_mag_db:
        mag_lin = 10 ** (mag_db / 20)
        total = float(np.sum(mag_lin ** 2))
        hf = float(np.sum(mag_lin[hf_mask] ** 2))
        per_frame_ratio.append(hf / total if total > 0 else 0.0)
    per_frame_ratio = np.asarray(per_frame_ratio)

    # Median magnitude across frames
    mag_db = np.median(np.array(all_mag_db), axis=0)

    # Energy above CD Nyquist (22.05 kHz)
    mag_linear = 10 ** (mag_db / 20)
    total_energy = float(np.sum(mag_linear ** 2))
    hf_energy = float(np.sum(mag_linear[hf_mask] ** 2))
    hf_ratio = hf_energy / total_energy if total_energy > 0 else 0.0

    # Max dB in HF region (absolute dBFS)
    max_hf_db = float(np.max(mag_db[hf_mask])) if hf_energy > 0 else -999.0

    # Frame-to-frame consistency of HF energy.
    # 1.0 = identical across frames (an upsampled file); low = dynamic (real signal).
    if len(per_frame_ratio) > 1 and per_frame_ratio.max() > 0:
        rng = per_frame_ratio.max() - per_frame_ratio.min()
        mean = per_frame_ratio.mean()
        frame_consistency = 1.0 - rng / (mean + rng + 1e-12)
    else:
        frame_consistency = 1.0

    # --- Noise floor slope in ultrasonic band (diagnostic only, NOT a trigger) ---
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

    # --- Brickwall detection at plausible SOURCE Nyquist frequencies ---
    # The defining signature of an upsample is a sharp spectral wall located at
    # the *source* rate's Nyquist frequency: real content right below it and a
    # large, sustained empty band right above it. We test standard source Nyquist
    # candidates rather than assuming CD (44.1 kHz), so this also catches e.g.
    # 22.05 kHz -> 192 kHz upsamples (whose wall sits at 11.025 kHz).
    #
    # Critically, "little ultrasonic content" is NOT evidence by itself — a
    # genuinely dark / band-limited master (classical, acoustic) also has little
    # up there. Only a localized wall at a plausible source Nyquist counts. This
    # is what stops us condemning honest dark recordings as fakes.
    def band_median_db(f_lo: float, f_hi: float) -> float:
        m = (freqs >= f_lo) & (freqs < f_hi)
        return float(np.median(mag_db[m])) if np.any(m) else -240.0

    ref_level = band_median_db(2000, 8000)   # a band that reliably has content
    nyquist = sr / 2
    best_edge = None  # (source_rate_hz, empty_db, content_below_db)
    for f_nyq in (11025, 22050, 24000, 44100, 48000):
        if f_nyq >= nyquist - 1000:
            continue
        below = band_median_db(f_nyq * 0.85, f_nyq * 0.98)
        above = band_median_db(f_nyq * 1.05, min(f_nyq * 1.6, nyquist - 200))
        empty_db = below - above
        content_below_db = below - ref_level
        # A real upsample wall: a big empty band above AND genuine content below.
        if empty_db > 30.0 and content_below_db > -35.0:
            if best_edge is None or empty_db > best_edge[1]:
                best_edge = (f_nyq * 2, empty_db, content_below_db)

    strength = "none"
    src_hint = None
    if best_edge is not None:
        src_hint, empty_db, _ = best_edge
        # A very large, clean wall is strong evidence; a moderate one is only
        # suspicious (downgraded so the caller reports "suspicious", not "fake").
        strength = "strong" if empty_db > 50.0 else "weak"

    return UpsamplingResult(
        is_suspected=strength != "none",
        strength=strength,
        hf_energy_ratio=hf_ratio,
        hf_energy_db=max_hf_db,
        ultrasonic_slope=slope,
        hf_frame_consistency=frame_consistency,
        source_rate_hint=src_hint,
    )


# ---------------------------------------------------------------------------
# 3. Fake 24-bit detection (enhanced)
# ---------------------------------------------------------------------------

def _detect_fake_24bit(
    samples: np.ndarray, bit_depth: int
) -> tuple[bool, float]:
    """Detect 16-bit content disguised in a 24-bit container.

    A genuine 24-bit signal uses its low bits: the lowest 8 bits of each sample
    carry real information and spread across most of 0-255. A 16-bit signal
    padded into 24 bits leaves those low bits empty / highly structured.

    We rely on LEVEL-INDEPENDENT features so the verdict doesn't flip with signal
    loudness (the old residual-ratio threshold had a zero-tolerance boundary at
    0.60 that misfired on genuine content):
      * Grid alignment — fraction of samples landing exactly on a 16-bit grid.
        We test BOTH common normalizations (divide by 32768 and by 32767) so a
        full-scale-style encoder can't evade detection with a one-ULP grid shift.
      * Low-8-bit entropy — how many distinct values the lowest 8 bits take.
      * Exact-zero residual — kept only at a near-exact tier (unambiguous padding).

    Returns:
        (low_bits_active, confidence_fake)
    """
    if bit_depth != 24:
        return True, 0.0

    lsb_24 = 1.0 / (2 ** 23)   # 24-bit LSB in the [-1, 1] float domain
    # Candidate 16-bit grid spacings: the standard power-of-two normalization
    # (/ 32768) and the full-scale variant (/ 32767) some encoders use.
    grid_steps = (1.0 / 32768, 1.0 / 32767)

    flat = samples.flatten()
    if len(flat) < 1000:
        return True, 0.0
    if float(np.mean(flat ** 2)) == 0:
        return True, 0.0

    # Sub-sample for performance (fixed seed -> deterministic verdicts).
    n_check = min(len(flat), 100_000)
    idx = np.random.default_rng(42).choice(len(flat), n_check, replace=False)
    subset = flat[idx]

    # Feature 1: grid alignment (best over candidate 16-bit grids).
    tol = lsb_24 * 0.5
    grid_ratio = 0.0
    for g in grid_steps:
        dist = np.abs(subset - np.round(subset / g) * g)
        grid_ratio = max(grid_ratio, float(np.mean(dist < tol)))

    # Feature 2: low-8-bit entropy of the 24-bit integer representation.
    int_24 = np.round(subset / lsb_24).astype(np.int64)
    unique_low8 = len(np.unique(int_24 & 0xFF))

    # Feature 3: exact-zero residual to a 16-bit grid (truly padded). Only the
    # near-exact tier is used — looser residual thresholds are level-dependent
    # and were a source of false positives on genuine 24-bit content.
    sig_power = max(float(np.mean(subset ** 2)), 1e-30)
    residual_ratio = min(
        float(np.mean((subset - np.round(subset / g) * g) ** 2)) for g in grid_steps
    ) / sig_power

    conf = 0.0
    # Grid alignment (primary, level-independent).
    if grid_ratio > 0.99:
        conf = max(conf, 0.95)
    elif grid_ratio > 0.95:
        conf = max(conf, 0.85)
    elif grid_ratio > 0.85:
        conf = max(conf, 0.72)
    # Low-8-bit entropy (genuine 24-bit spreads across most of 0-255).
    if unique_low8 < 8:
        conf = max(conf, 0.90)
    elif unique_low8 < 32:
        conf = max(conf, 0.70)
    elif unique_low8 < 96:
        conf = max(conf, 0.45)
    # Exact-zero residual (unambiguous padding).
    if residual_ratio < 1e-13:
        conf = max(conf, 0.90)

    conf = min(1.0, conf)
    # Flag fake only at high confidence, with a clear margin below the old 0.60
    # boundary (and aligned with hires.FAKE_THRESHOLD = 0.70).
    low_bits_active = conf < 0.70
    return low_bits_active, conf
