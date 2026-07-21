"""Generate test audio files to evaluate authenticity detection accuracy."""
import numpy as np
import soundfile as sf
from scipy import signal
from pathlib import Path

OUT = Path(__file__).parent / "testdata"
SR_HIRES = 96000
SR_CD = 44100
DURATION = 3.0  # seconds
BIT_HIRES = 24
BIT_CD = 16


def pink_noise_psd(freqs, alpha=1.0):
    """Generate pink noise (1/f^alpha) in frequency domain."""
    n = len(freqs)
    # Extend to full spectrum for IFFT
    full_n = 2 * (n - 1)
    mag = np.zeros(full_n // 2 + 1)
    mag[1:] = 1.0 / np.sqrt(freqs[1:]) ** alpha
    mag[0] = 0
    # Random phase
    phases = np.random.uniform(0, 2 * np.pi, len(mag))
    mag[0] = 0
    f_spectrum = mag * np.exp(1j * phases)
    # IFFT to time domain
    full_spectrum = np.zeros(full_n, dtype=complex)
    full_spectrum[: len(f_spectrum)] = f_spectrum
    # Ensure conjugate symmetry
    for i in range(1, len(f_spectrum)):
        full_spectrum[full_n - i] = np.conj(f_spectrum[i])
    sig = np.fft.ifft(full_spectrum).real
    sig /= np.max(np.abs(sig)) * 1.1
    return sig


def pink_noise(sr, duration, alpha=1.0):
    """Generate pink noise of given sample rate and duration."""
    n = int(sr * duration)
    # Make n a nice number for FFT
    n_fft = 2 ** int(np.ceil(np.log2(n)))
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    sig = pink_noise_psd(freqs, alpha)
    return sig[:n]


def write_wav(path, sig, sr, bit_depth):
    """Write WAV file with specified bit depth."""
    subtype_map = {16: 'PCM_16', 24: 'PCM_24', 32: 'PCM_32'}
    sf.write(str(path), sig, sr, subtype=subtype_map[bit_depth])


def write_flac(path, sig, sr, bit_depth):
    """Write FLAC file."""
    subtype_map = {16: 'PCM_16', 24: 'PCM_24'}
    sf.write(str(path), sig, sr, subtype=subtype_map[bit_depth])


# ===== 1. Genuine 96kHz/24-bit (control) =====
print("1/7: Genuine 96kHz/24-bit pink noise...")
sr = SR_HIRES
genuine = pink_noise(sr, DURATION)
write_wav(OUT / "01_genuine_96k_24bit.wav", genuine, sr, 24)
write_flac(OUT / "01_genuine_96k_24bit.flac", genuine, sr, 24)

# ===== 2. Genuine 44.1kHz/16-bit (CD quality control) =====
print("2/7: CD quality 44.1kHz/16-bit pink noise...")
sr = SR_CD
cd_quality = pink_noise(sr, DURATION)
write_wav(OUT / "02_cd_44k_16bit.wav", cd_quality, sr, 16)
write_flac(OUT / "02_cd_44k_16bit.flac", cd_quality, sr, 16)

# ===== 3. Upsampled fake: 44.1k -> 96k =====
print("3/7: Upsampled fake (44.1k -> 96k)...")
sr_src = SR_CD
sr_dst = SR_HIRES
src_sig = pink_noise(sr_src, DURATION)
# Apply a typical low-pass filter first (simulates CD mastering chain)
b, a = signal.butter(8, 20000 / (sr_src / 2), 'low')
src_filtered = signal.filtfilt(b, a, src_sig)
# Resample using scipy (which uses a decent resampler - not the worst case, realistic)
n_dst = int(len(src_filtered) * sr_dst / sr_src)
upsampled = signal.resample(src_filtered, n_dst)
upsampled /= np.max(np.abs(upsampled)) * 1.1
write_wav(OUT / "03_upsampled_44k_to_96k_24bit.wav", upsampled, sr_dst, 24)
write_flac(OUT / "03_upsampled_44k_to_96k_24bit.flac", upsampled, sr_dst, 24)

# ===== 4. Fake 24-bit: 16-bit -> padded to 24-bit =====
print("4/7: Fake 24-bit (16-bit padded)...")
sr = SR_HIRES
sig = pink_noise(sr, DURATION)
# Quantize to 16-bit range, write as 16-bit WAV first, then re-read as float
# This ensures the values are truly aligned to a 16-bit grid
tmp_16 = OUT / "_tmp_16bit.wav"
write_wav(tmp_16, sig, sr, 16)
sig_16_read, sr2 = sf.read(str(tmp_16))
# Now write as 24-bit — the values stay on the 16-bit grid
write_wav(OUT / "04_fake24bit_padded.wav", sig_16_read, sr, 24)
write_flac(OUT / "04_fake24bit_padded.flac", sig_16_read, sr, 24)
tmp_16.unlink()

# ===== 5. MP3-sourced fake: brickwall cutoff -> saved as FLAC =====
print("5/7: MP3-sourced fake (brickwall cutoff -> FLAC)...")
sr = 44100
sig_mp3_in = pink_noise(sr, DURATION)
# Simulate MP3-style brickwall at ~16kHz via FFT zeroing (perfect cutoff)
n_fft = len(sig_mp3_in)
freqs_fft = np.fft.fftfreq(n_fft, 1/sr)
spec = np.fft.fft(sig_mp3_in)
spec[np.abs(freqs_fft) > 16000] = 0  # hard brickwall at 16kHz
sig_cutoff = np.fft.ifft(spec).real
sig_cutoff /= np.max(np.abs(sig_cutoff)) * 1.1
write_flac(OUT / "05_mp3_sourced_cutoff.flac", sig_cutoff, sr, 16)

# ===== 6. Extreme fake: 22.05k upsampled to 192k =====
print("6/7: Extreme upsample fake (22k -> 192k)...")
sr_src = 22050
sr_dst = 192000
src_sig = pink_noise(sr_src, DURATION)
b, a = signal.butter(6, 10000 / (sr_src / 2), 'low')
src_filtered = signal.filtfilt(b, a, src_sig)
n_dst = int(len(src_filtered) * sr_dst / sr_src)
extreme_up = signal.resample(src_filtered, n_dst)
extreme_up /= np.max(np.abs(extreme_up)) * 1.1
write_wav(OUT / "06_extreme_upsampled_22k_to_192k.wav", extreme_up, sr_dst, 24)

# ===== 7. Genuine 192kHz/24-bit =====
print("7/7: Genuine 192kHz/24-bit...")
sr = 192000
genuine_192 = pink_noise(sr, DURATION)
write_wav(OUT / "07_genuine_192k_24bit.wav", genuine_192, sr, 24)

print(f"\nAll test files generated in {OUT}/")
print("Files:")
for f in sorted(OUT.glob("*")):
    size_mb = f.stat().st_size / 1e6
    print(f"  {f.name} ({size_mb:.1f}MB)")
