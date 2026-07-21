"""Unified audio I/O — read any format, return numpy arrays."""

import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf


@dataclass
class AudioData:
    """Decoded audio data with metadata."""

    samples: np.ndarray  # shape: (channels, n_samples) — always float64, normalized to [-1, 1]
    sample_rate: int
    channels: int
    duration_s: float
    bit_depth: int  # reported bit depth from file metadata
    format: str  # file format label (FLAC, WAV, etc.)
    subtype: str  # codec subtype (PCM_16, PCM_24, FLOAT, etc.)
    file_path: Path

    @property
    def n_samples(self) -> int:
        return self.samples.shape[1]

    @property
    def is_mono(self) -> bool:
        return self.channels == 1


def read_audio(file_path: str | Path) -> AudioData:
    """Read an audio file and return normalized AudioData.

    All samples are returned as float64 in the [-1, 1] range.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        info = sf.info(str(path))
        samples, sample_rate = sf.read(str(path), dtype="float64", always_2d=False)

    # Normalize integer formats to [-1, 1]
    # soundfile already does this for float64 reads, but be explicit
    if samples.dtype != np.float64:
        samples = samples.astype(np.float64)

    # Ensure shape is (channels, n_samples)
    if samples.ndim == 1:
        samples = samples[np.newaxis, :]
    else:
        samples = samples.T

    duration = len(samples[0]) / sample_rate if sample_rate > 0 else 0.0

    # Determine reported bit depth
    subtype = info.subtype
    bit_depth = _bit_depth_from_subtype(subtype)

    return AudioData(
        samples=samples,
        sample_rate=sample_rate,
        channels=info.channels,
        duration_s=duration,
        bit_depth=bit_depth,
        format=info.format,
        subtype=subtype,
        file_path=path,
    )


def _bit_depth_from_subtype(subtype: str) -> int:
    """Extract bit depth from soundfile subtype string."""
    # Map common subtypes to bit depth
    mapping = {
        "PCM_16": 16,
        "PCM_24": 24,
        "PCM_32": 32,
        "FLOAT": 32,
        "DOUBLE": 64,
        "PCM_S8": 8,
        "PCM_U8": 8,
    }
    return mapping.get(subtype, 0)
