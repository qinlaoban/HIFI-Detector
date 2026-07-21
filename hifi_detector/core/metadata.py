"""File metadata extraction and analysis."""

from dataclasses import dataclass

import soundfile as sf

from .audio_io import AudioData


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
        )


def extract_metadata(audio: AudioData) -> MetadataReport:
    """Extract and format metadata from an audio file."""
    return MetadataReport.from_audio(audio)
