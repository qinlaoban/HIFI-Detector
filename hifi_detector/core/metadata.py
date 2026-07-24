"""File metadata extraction and analysis."""

from dataclasses import dataclass

import soundfile as sf

from .audio_io import AudioData

# Uncompressed (linear PCM) formats
_UNCOMPRESSED_FORMATS = {"wav", "aiff", "aif"}


@dataclass
class MetadataReport:
    """Structured metadata report."""

    file_path: str
    file_size_mb: float
    file_size_bytes: int
    format: str
    subtype: str
    sample_rate: int
    bit_depth: int
    channels: int
    duration_s: float
    duration_display: str
    bitrate_kbps: int | None
    subformat_info: str | None
    bitrate_pcm_kbps: int | None           # uncompressed PCM equivalent bitrate
    bitrate_low: bool                       # True if actual bitrate is suspiciously low

    @staticmethod
    def from_audio(audio: AudioData) -> "MetadataReport":
        path = audio.file_path
        raw_bytes = path.stat().st_size
        file_size = raw_bytes / (1000 * 1000)  # decimal MB (macOS convention)

        # Duration display
        mins, secs = divmod(int(audio.duration_s), 60)
        duration_display = f"{mins}:{secs:02d}"

        # Estimate bitrate
        if audio.duration_s > 0:
            bitrate = int((raw_bytes * 8) / audio.duration_s / 1000)
        else:
            bitrate = None

        # Uncompressed PCM equivalent and low-bitrate check
        pcm_kbps = int(audio.sample_rate * audio.bit_depth * audio.channels / 1000)
        is_low = _check_bitrate_low(
            bitrate, pcm_kbps,
            fmt=audio.format.lower(),
            duration_s=audio.duration_s,
        )

        # Subformat detail
        try:
            sfinfo = sf.info(str(path))
            subformat = getattr(sfinfo, "subtype_info", None)
        except Exception:
            subformat = None

        return MetadataReport(
            file_path=str(path.name),
            file_size_mb=round(file_size, 2),
            file_size_bytes=raw_bytes,
            format=audio.format,
            subtype=audio.subtype,
            sample_rate=audio.sample_rate,
            bit_depth=audio.bit_depth,
            channels=audio.channels,
            duration_s=audio.duration_s,
            duration_display=duration_display,
            bitrate_kbps=bitrate,
            subformat_info=subformat,
            bitrate_pcm_kbps=pcm_kbps,
            bitrate_low=is_low,
        )


def _check_bitrate_low(
    actual_kbps: int | None,
    pcm_kbps: int,
    *,
    fmt: str,
    duration_s: float,
) -> bool:
    """Check if actual bitrate is suspiciously low for the format.

    For uncompressed formats (WAV/AIFF), bitrate should equal the PCM rate
    exactly. For compressed (FLAC etc.), a well-mastered music track
    typically compresses to 40-70% of PCM. Below 30% is worth flagging —
    may indicate an extremely sparse source (silence, pure tone) or a
    lossy origin hiding in a lossless container.

    Short files (<5s) are exempt: the ratio is unreliable on tiny samples.
    """
    if actual_kbps is None or pcm_kbps == 0:
        return False
    if duration_s < 5:
        return False

    ratio = actual_kbps / pcm_kbps

    if fmt in _UNCOMPRESSED_FORMATS:
        # Uncompressed: tolerate 2% mismatch for header/metadata
        return ratio < 0.98
    else:
        # Compressed: <30% of PCM is suspicious
        return ratio < 0.30


def extract_metadata(audio: AudioData) -> MetadataReport:
    """Extract and format metadata from an audio file."""
    return MetadataReport.from_audio(audio)
