"""Generate test audio files with realistic dynamics for authenticity detection evaluation.

Key improvements over v1:
- Time-varying amplitude envelope → realistic DR (dynamic range)
- Peak normalization to -1.5 dBTP → no clipping
- Longer duration (10s) → reliable DR measurement
- Genuine files: full bandwidth, DR 12-16
- Fake files: keep forgery artifacts but reasonable DR

Expected verdicts (Web UI logic):
  01_genuine_96k_24bit      → CLEAN or HIGH_QUALITY
  02_cd_44k_16bit           → CLEAN
  03_upsampled_44k_to_96k   → ISSUES (upsampling detected)
  04_fake24bit_padded       → WARN or ISSUES (fake 24-bit)
  05_mp3_sourced_cutoff     → WARN or ISSUES (frequency cutoff)
  06_extreme_upsampled      → ISSUES (extreme upsampling)
  07_genuine_192k_24bit     → CLEAN or HIGH_QUALITY
"""
import numpy as np
import soundfile as sf
from scipy import signal as sig
from pathlib import Path

OUT = Path(__file__).parent / "testdata"
SR_HIRES = 96000
SR_CD = 44100
DURATION = 30.0  # seconds — enough windows for reliable DR measurement
PEAK_DBTP = -1.5  # target true peak


# ──────────────────────────────────────────────
# Signal generation helpers
# ──────────────────────────────────────────────

def pink_noise(sr, duration, alpha=1.0, seed=None):
    """Generate pink noise (1/f^alpha) via Voss-McCartney method."""
    rng = np.random.default_rng(seed)
    n = int(sr * duration)
    # Use filtered white noise for stable 1/f spectrum
    n_fft = 2 ** int(np.ceil(np.log2(n)))
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    mag = np.zeros_like(freqs)
    mag[1:] = 1.0 / np.sqrt(freqs[1:]) ** alpha
    mag[0] = 0
    phases = rng.uniform(0, 2 * np.pi, len(mag))
    spectrum = mag * np.exp(1j * phases)
    time_sig = np.fft.irfft(spectrum, n=n_fft)[:n]
    time_sig /= np.max(np.abs(time_sig))
    return time_sig


def musical_envelope(n_samples, sr, target_dr=14, seed=42):
    """Create an amplitude envelope that produces a specific DR value.

    DR14 formula: DR = 20*log10(top20_avg / overall_avg)
    where top20 = loudest 20% of 0.5s windows.

    Key: ALL top-20% windows must be 'loud' (high amplitude).
    Bottom 80% must be very quiet so overall_avg is low enough.

    Math: loud=1.0 for n_top windows, quiet=a_q for n_quiet windows
      top20_avg = 1.0
      overall_avg = sqrt((n_top + n_quiet*a_q^2) / n_total)
      DR = 20*log10(1.0 / overall_avg)
      => a_q = sqrt((n_total / 10^(DR/10) - n_top) / n_quiet)
    """
    rng = np.random.default_rng(seed)
    n = n_samples
    duration = n / sr
    window_s = 0.5
    n_windows = int(duration / window_s)
    win_samples = int(window_s * sr)

    n_top = max(1, int(np.ceil(n_windows * 0.2)))
    n_quiet = n_windows - n_top

    # Calculate quiet amplitude for target DR
    # With top20_avg = 1.0, solve for a_quiet
    power_ratio = 10 ** (target_dr / 10)
    a_quiet_sq = (n_windows / power_ratio - n_top) / n_quiet
    a_quiet = np.sqrt(max(a_quiet_sq, 1e-10))

    # Build window amplitudes
    # Loud windows: all at 1.0 (or slight gradient for realism)
    loud_amps = np.ones(n_top) * 1.0
    # Quiet windows: random variation around a_quiet (±40%)
    quiet_amps = rng.uniform(a_quiet * 0.6, a_quiet * 1.4, n_quiet)
    # Normalize quiet RMS to target
    current_q_rms = np.sqrt(np.mean(quiet_amps ** 2))
    if current_q_rms > 1e-10:
        quiet_amps *= a_quiet / current_q_rms
    quiet_amps = np.clip(quiet_amps, 1e-6, 0.5)  # must stay below loud

    # Assemble and shuffle
    window_amps = np.concatenate([loud_amps, quiet_amps])
    rng.shuffle(window_amps)

    # Fine-tune quiet windows to hit exact DR
    for _ in range(50):
        rms_sorted = np.sort(window_amps)[::-1]
        top_rms = rms_sorted[:n_top]
        t20 = np.sqrt(np.mean(top_rms ** 2))
        ov = np.sqrt(np.mean(window_amps ** 2))
        if ov < 1e-10:
            break
        current_dr = 20 * np.log10(t20 / ov)
        if abs(current_dr - target_dr) < 0.3:
            break
        mask = window_amps < 0.5  # only adjust quiet
        if current_dr < target_dr:
            window_amps[mask] *= 0.8  # make quieter
        else:
            window_amps[mask] *= 1.2  # make louder

    # Expand to per-sample
    ramp = max(int(sr * 0.003), 1)  # 3ms ramp
    env = np.zeros(n)
    for i, amp in enumerate(window_amps):
        start = i * win_samples
        end = min(start + win_samples, n)
        env[start:end] = amp

    from scipy.ndimage import uniform_filter1d
    env = uniform_filter1d(env, size=ramp)

    return env


def remove_dc(audio, sr):
    """Remove DC offset using a high-pass filter at 10 Hz."""
    from scipy.signal import butter, filtfilt
    b, a = butter(2, 10 / (sr / 2), 'high')
    return filtfilt(b, a, audio)


def normalize_to_peak(audio, target_dbtp=-1.5):
    """Normalize audio so true peak equals target dBTP."""
    # True peak: upsample 4x and find max
    from scipy.signal import resample_poly
    upsampled = resample_poly(audio, 4, 1)
    true_peak = np.max(np.abs(upsampled))
    if true_peak < 1e-10:
        return audio
    target_linear = 10 ** (target_dbtp / 20)
    return audio * (target_linear / true_peak)


def write_wav(path, data, sr, bit_depth):
    subtype_map = {16: 'PCM_16', 24: 'PCM_24', 32: 'FLOAT'}
    sf.write(str(path), data, sr, subtype=subtype_map[bit_depth])


def write_flac(path, data, sr, bit_depth):
    subtype_map = {16: 'PCM_16', 24: 'PCM_24'}
    sf.write(str(path), data, sr, subtype=subtype_map[bit_depth])


def make_stereo(mono, width=0.3, seed=123):
    """Create stereo from mono with slight decorrelation."""
    rng = np.random.default_rng(seed)
    delay_samples = int(rng.integers(1, 50))
    left = mono.copy()
    right = np.roll(mono, delay_samples)
    # Add tiny noise difference
    right += rng.normal(0, 0.001, len(right))
    return np.column_stack([left, right])


# ──────────────────────────────────────────────
# Test case generators
# ──────────────────────────────────────────────

def gen_genuine_hires(sr, bit_depth, seed, prefix):
    """Generate a genuine high-resolution audio file.
    Full bandwidth content, realistic dynamics (DR ~14).
    """
    print(f"  Generating genuine {sr/1000:.0f}kHz/{bit_depth}-bit...")
    n = int(sr * DURATION)
    base = pink_noise(sr, DURATION, seed=seed)
    env = musical_envelope(n, sr, seed=seed + 100)
    audio = base * env
    audio = remove_dc(audio, sr)
    audio = normalize_to_peak(audio, PEAK_DBTP)
    stereo = make_stereo(audio, seed=seed + 200)

    write_wav(OUT / f"{prefix}.wav", stereo, sr, bit_depth)
    write_flac(OUT / f"{prefix}.flac", stereo, sr, bit_depth)
    return stereo, sr


def gen_cd_quality(seed, prefix):
    """Generate genuine CD-quality audio.
    Bandwidth limited to 20kHz (natural for 44.1kHz SR), DR ~12.
    """
    print(f"  Generating CD-quality 44.1kHz/16-bit...")
    sr = SR_CD
    n = int(sr * DURATION)
    base = pink_noise(sr, DURATION, seed=seed)
    # Gentle rolloff above 19kHz (realistic CD mastering)
    b, a = sig.butter(4, 19000 / (sr / 2), 'low')
    base = sig.filtfilt(b, a, base)
    env = musical_envelope(n, sr, seed=seed + 100)
    audio = base * env
    audio = remove_dc(audio, sr)
    audio = normalize_to_peak(audio, PEAK_DBTP)
    stereo = make_stereo(audio, seed=seed + 200)

    write_wav(OUT / f"{prefix}.wav", stereo, sr, 16)
    write_flac(OUT / f"{prefix}.flac", stereo, sr, 16)
    return stereo, sr


def gen_upsampled_44k_to_96k(seed, prefix):
    """Upsample from 44.1kHz to 96kHz.
    The detection should catch the brickwall at CD Nyquist (22.05kHz).
    """
    print(f"  Generating upsampled fake (44.1k → 96k)...")
    sr_src = SR_CD
    sr_dst = SR_HIRES
    n_src = int(sr_src * DURATION)
    base = pink_noise(sr_src, DURATION, seed=seed)
    # Band-limit to 20kHz (typical CD mastering)
    b, a = sig.butter(8, 20000 / (sr_src / 2), 'low')
    base = sig.filtfilt(b, a, base)
    env = musical_envelope(n_src, sr_src, seed=seed + 100)
    base = base * env
    base = remove_dc(base, sr_src)
    base = normalize_to_peak(base, PEAK_DBTP)

    # Resample to 96kHz
    n_dst = int(len(base) * sr_dst / sr_src)
    upsampled = sig.resample(base, n_dst)
    upsampled = normalize_to_peak(upsampled, PEAK_DBTP)
    stereo = make_stereo(upsampled, seed=seed + 200)

    write_wav(OUT / f"{prefix}.wav", stereo, sr_dst, 24)
    write_flac(OUT / f"{prefix}.flac", stereo, sr_dst, 24)
    return stereo, sr_dst


def gen_fake_24bit_padded(seed, prefix):
    """Generate 16-bit content padded to 24-bit container.
    Lower 8 bits should be inactive (all zeros).
    """
    print(f"  Generating fake 24-bit (16-bit padded)...")
    sr = SR_HIRES
    n = int(sr * DURATION)
    base = pink_noise(sr, DURATION, seed=seed)
    env = musical_envelope(n, sr, seed=seed + 100)
    audio = base * env
    audio = remove_dc(audio, sr)
    audio = normalize_to_peak(audio, PEAK_DBTP)

    # Quantize to 16-bit grid, then save as 24-bit
    # Write as 16-bit first, re-read to ensure true 16-bit quantization
    tmp_path = OUT / "_tmp_16bit.wav"
    stereo_16 = make_stereo(audio, seed=seed + 200)
    write_wav(tmp_path, stereo_16, sr, 16)
    stereo_16_read, _ = sf.read(str(tmp_path))
    tmp_path.unlink()

    write_wav(OUT / f"{prefix}.wav", stereo_16_read, sr, 24)
    write_flac(OUT / f"{prefix}.flac", stereo_16_read, sr, 24)
    return stereo_16_read, sr


def gen_mp3_sourced_cutoff(seed, prefix):
    """Simulate MP3-sourced audio: brickwall cutoff at ~16kHz.
    Typical of 128kbps MP3 encoding.
    """
    print(f"  Generating MP3-sourced fake (cutoff at 16kHz)...")
    sr = SR_CD
    n = int(sr * DURATION)
    base = pink_noise(sr, DURATION, seed=seed)
    # Hard brickwall at 16kHz via FFT zeroing
    n_fft = len(base)
    freqs = np.fft.fftfreq(n_fft, 1 / sr)
    spec = np.fft.fft(base)
    spec[np.abs(freqs) > 16000] = 0
    base = np.fft.ifft(spec).real
    env = musical_envelope(n, sr, seed=seed + 100)
    audio = base * env
    audio = remove_dc(audio, sr)
    audio = normalize_to_peak(audio, PEAK_DBTP)
    stereo = make_stereo(audio, seed=seed + 200)

    write_flac(OUT / f"{prefix}.flac", stereo, sr, 16)
    return stereo, sr


def gen_extreme_upsampled_22k_to_192k(seed, prefix):
    """Extreme upsample: 22.05kHz source → 192kHz container.
    Source has bandwidth only to ~10kHz, should be clearly detectable.
    """
    print(f"  Generating extreme upsample fake (22k → 192k)...")
    sr_src = 22050
    sr_dst = 192000
    n_src = int(sr_src * DURATION)
    base = pink_noise(sr_src, DURATION, seed=seed)
    # Band-limit to 10kHz (typical low-quality source)
    b, a = sig.butter(6, 10000 / (sr_src / 2), 'low')
    base = sig.filtfilt(b, a, base)
    env = musical_envelope(n_src, sr_src, seed=seed + 100)
    base = base * env
    base = remove_dc(base, sr_src)
    base = normalize_to_peak(base, PEAK_DBTP)

    # Resample to 192kHz
    n_dst = int(len(base) * sr_dst / sr_src)
    upsampled = sig.resample(base, n_dst)
    upsampled = normalize_to_peak(upsampled, PEAK_DBTP)
    stereo = make_stereo(upsampled, seed=seed + 200)

    write_wav(OUT / f"{prefix}.wav", stereo, sr_dst, 24)
    return stereo, sr_dst


def gen_genuine_192k(seed, prefix):
    """Generate genuine 192kHz/24-bit audio.
    Full ultrasonic content, realistic dynamics (DR ~15).
    """
    print(f"  Generating genuine 192kHz/24-bit...")
    sr = 192000
    n = int(sr * DURATION)
    base = pink_noise(sr, DURATION, seed=seed)
    env = musical_envelope(n, sr, seed=seed + 100)
    audio = base * env
    audio = remove_dc(audio, sr)
    audio = normalize_to_peak(audio, PEAK_DBTP)
    stereo = make_stereo(audio, seed=seed + 200)

    write_wav(OUT / f"{prefix}.wav", stereo, sr, 24)
    return stereo, sr


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)

    # Clean old test files
    for old in OUT.glob("*.*"):
        if old.suffix in {'.flac', '.wav'}:
            old.unlink()

    np.random.seed(42)

    print("1/7: Genuine 96kHz/24-bit")
    gen_genuine_hires(96000, 24, seed=1000, prefix="01_genuine_96k_24bit")

    print("2/7: CD-quality 44.1kHz/16-bit")
    gen_cd_quality(seed=2000, prefix="02_cd_44k_16bit")

    print("3/7: Upsampled fake (44.1k → 96k)")
    gen_upsampled_44k_to_96k(seed=3000, prefix="03_upsampled_44k_to_96k_24bit")

    print("4/7: Fake 24-bit (16-bit padded)")
    gen_fake_24bit_padded(seed=4000, prefix="04_fake24bit_padded")

    print("5/7: MP3-sourced fake (brickwall at 16kHz)")
    gen_mp3_sourced_cutoff(seed=5000, prefix="05_mp3_sourced_cutoff")

    print("6/7: Extreme upsample fake (22k → 192k)")
    gen_extreme_upsampled_22k_to_192k(seed=6000, prefix="06_extreme_upsampled_22k_to_192k")

    print("7/7: Genuine 192kHz/24-bit")
    gen_genuine_192k(seed=7000, prefix="07_genuine_192k_24bit")

    print(f"\n✓ All test files generated in {OUT}/")
    print("\nFiles:")
    total_mb = 0
    for f in sorted(OUT.glob("*.*")):
        size_mb = f.stat().st_size / 1e6
        total_mb += size_mb
        print(f"  {f.name:48s}  {size_mb:.1f} MB")
    print(f"  {'TOTAL':48s}  {total_mb:.1f} MB")
