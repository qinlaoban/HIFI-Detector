"""API routes for HIFI Detector Web UI."""

import json
import tempfile
import uuid
import hashlib
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path

import numpy as np
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import List

from ..core.audio_io import read_audio, AudioData
from ..core.metadata import extract_metadata
from ..core.quality import analyze_quality
from ..core.loudness import analyze_loudness
from ..core.dynamic_range import analyze_dynamic_range
from ..core.authenticity import analyze_authenticity
from ..core.hires import verify_hires

router = APIRouter(prefix="/api")

# Maximum upload size: 600 MB
MAX_UPLOAD_SIZE = 600 * 1024 * 1024

# Batch limits
MAX_BATCH_FILES = 30

# LRU cache: file_id -> (decoded AudioData, file_path)
# Limited to 20 entries to prevent memory/disk exhaustion
_MAX_CACHE_ENTRIES = 20
_file_cache: OrderedDict[str, tuple[AudioData, Path]] = OrderedDict()


def _cache_put(fid: str, audio: AudioData, path: Path):
    """Add entry to cache, evicting oldest if over limit."""
    if fid in _file_cache:
        _file_cache.move_to_end(fid)
    else:
        if len(_file_cache) >= _MAX_CACHE_ENTRIES:
            _, (_, old_path) = _file_cache.popitem(last=False)
            old_path.unlink(missing_ok=True)
        _file_cache[fid] = (audio, path)


def _file_id(file_path: Path) -> str:
    """Generate a short file id."""
    h = hashlib.sha256(str(file_path).encode()).hexdigest()[:12]
    return h


def _sanitize(obj):
    """Replace non-finite floats (inf / -inf / nan) with None for JSON compliance.

    Silent or near-silent files produce -inf in some metrics (e.g. LUFS, RMS);
    JSON cannot represent those, so map them to null before serializing.
    """
    if isinstance(obj, (float, np.floating)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def _build_verdict(quality, loudness, dr, authenticity) -> str:
    """Compute tiered verdict from analysis results."""
    clip = quality.clip_samples > 0
    tp_max = max(loudness.true_peak_db_l, loudness.true_peak_db_r or -999)
    tp_severe = tp_max > 0.5
    tp_notice = 0 < tp_max <= 0.5
    dr_severe = dr.dr_official < 5
    dr_notice = 5 <= dr.dr_official < 7
    dc_issue = quality.dc_offset_pct > 0.1
    auth_susp = authenticity.verdict == "suspicious"
    auth_ambig = authenticity.verdict == "ambiguous"

    if clip or auth_susp:
        return "ISSUES"
    elif tp_severe or dr_severe or auth_ambig:
        return "WARN"
    elif dc_issue or tp_notice or dr_notice:
        return "WARN"
    elif dr.dr_official >= 14:
        return "HIGH_QUALITY"
    else:
        return "CLEAN"


def _run_analysis(file: UploadFile) -> dict:
    """Run full analysis on a single uploaded file. Returns result dict or error."""
    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower()
    allowed = {".flac", ".wav", ".mp3", ".aiff", ".aif", ".ogg", ".opus", ".m4a", ".alac", ".ape", ".wv"}
    if ext not in allowed:
        return {"filename": filename, "error": f"Unsupported format: {ext}"}

    content = file.file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        return {"filename": filename, "error": f"File too large (max {MAX_UPLOAD_SIZE // (1024*1024)} MB)"}

    suffix = ext or ".tmp"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    fid = _file_id(tmp_path)

    try:
        audio = read_audio(tmp_path)
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        return {"filename": filename, "error": str(e)}

    _cache_put(fid, audio, tmp_path)

    try:
        meta = extract_metadata(audio)
        quality = analyze_quality(audio)
        loudness = analyze_loudness(audio)
        dr = analyze_dynamic_range(audio)
        authenticity = analyze_authenticity(audio)
        hires = verify_hires(audio, authenticity)
    except Exception as e:
        return {"filename": filename, "error": f"Analysis failed: {e}"}

    verdict = _build_verdict(quality, loudness, dr, authenticity)

    return {
        "file_id": fid,
        "filename": filename,
        "verdict": verdict,
        "hires": asdict(hires),
        "metadata": {
            "format": meta.format,
            "subtype": meta.subtype,
            "sample_rate": meta.sample_rate,
            "bit_depth": meta.bit_depth,
            "channels": meta.channels,
            "duration_s": round(meta.duration_s, 2),
            "file_size_mb": meta.file_size_mb,
            "file_size_bytes": meta.file_size_bytes,
            "bitrate_kbps": meta.bitrate_kbps,
            "bitrate_pcm_kbps": meta.bitrate_pcm_kbps,
            "bitrate_low": meta.bitrate_low,
        },
        "quality": {
            "clipping": {
                "samples": quality.clip_samples,
                "ratio_pct": quality.clip_ratio_pct,
            },
            "dc_offset_pct": quality.dc_offset_pct,
            "channel_balance_db": quality.balance_diff_db,
            "effective_bits": quality.effective_bits,
            "bit_depth_suspicious": quality.bit_depth_suspicious,
        },
        "loudness": {
            "rms_l_dbfs": loudness.rms_db_l,
            "rms_r_dbfs": loudness.rms_db_r,
            "true_peak_l_dbtp": loudness.true_peak_db_l,
            "true_peak_r_dbtp": loudness.true_peak_db_r,
            "integrated_lufs": loudness.integrated_lufs,
            "loudness_range_lu": loudness.loudness_range_lu,
        },
        "dynamic_range": {
            "dr_official": dr.dr_official,
            "dr_precise_avg_db": dr.dr_precise_avg_db,
            "dr_precise_per_channel": dr.dr_precise_db,
            "rating": dr.rating,
            "rating_color": dr.rating_color,
            "boundary_risk": dr.boundary_risk,
        },
        "authenticity": {
            "verdict": authenticity.verdict,
            "is_suspicious": authenticity.is_suspicious,
            "overall_confidence": authenticity.overall_confidence,
            "cutoff_freq_hz": authenticity.cutoff_freq_hz,
            "cutoff_suspected_codec": authenticity.cutoff_suspected_codec,
            "has_sharp_cutoff": authenticity.has_sharp_cutoff,
            "cutoff_confidence": authenticity.cutoff_confidence,
            "is_suspected_upsampled": authenticity.is_suspected_upsampled,
            "upsample_strength": authenticity.upsample_strength,
            "hf_energy_ratio": authenticity.hf_energy_ratio,
            "hf_energy_db": authenticity.hf_energy_db,
            "ultrasonic_slope": authenticity.ultrasonic_slope,
            "hf_frame_consistency": authenticity.hf_frame_consistency,
            "natural_ultrasonic": authenticity.natural_ultrasonic,
            "upsample_source_rate_hint": authenticity.upsample_source_rate_hint,
            "low_bits_active": authenticity.low_bits_active,
            "fake_24bit_confidence": authenticity.fake_24bit_confidence,
            "suspicion_reasons": authenticity.suspicion_reasons,
        },
    }


@router.post("/analyze")
def analyze_audio(file: UploadFile = File(...)):
    """Upload and analyze an audio file. Returns full analysis report."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    result = _run_analysis(file)
    if "error" in result:
        status = 413 if "too large" in result["error"] else 400
        raise HTTPException(status, result["error"])
    return _sanitize(result)


@router.post("/analyze/batch")
def analyze_batch(files: List[UploadFile] = File(...)):
    """Upload and analyze multiple audio files. Returns list of reports."""
    if not files:
        raise HTTPException(400, "No files provided")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(400, f"Too many files (max {MAX_BATCH_FILES})")

    results = []
    for f in files:
        results.append(_run_analysis(f))
    return _sanitize({"total": len(results), "results": results})


@router.get("/spectrogram/{file_id}")
def get_spectrogram(
    file_id: str,
    channel: int = Query(0, ge=0, le=7),
    resolution: str = Query("medium", pattern="^(low|medium|high)$"),
):
    """Generate spectrogram data for interactive visualization.

    Returns time, frequency, and magnitude arrays for Plotly.js heatmap.
    """
    cached = _file_cache.get(file_id)
    if cached is None:
        raise HTTPException(404, "File not found. Re-upload the audio file.")

    audio, _ = cached

    if channel >= audio.channels:
        channel = 0

    # STFT parameters
    nfft_map = {"low": 1024, "medium": 2048, "high": 4096}
    n_fft = nfft_map[resolution]
    hop_length = n_fft // 4
    nperseg = n_fft

    signal = audio.samples[channel]

    from scipy.signal import spectrogram as spgram

    freqs, times, Sxx = spgram(
        signal,
        fs=audio.sample_rate,
        nperseg=nperseg,
        noverlap=nperseg - hop_length,
        nfft=n_fft,
        window="hann",
        scaling="density",
    )

    # Convert to dB
    Sxx_db = 10 * np.log10(np.maximum(Sxx, 1e-20))
    # Clip to reasonable range
    Sxx_db = np.clip(Sxx_db, -140, 0)

    # Downsample for transmission (too much data otherwise)
    max_points = 2000
    if len(times) > max_points:
        step = len(times) // max_points
        times = times[::step]
        Sxx_db = Sxx_db[:, ::step]

    # Quantize to reduce JSON size
    Sxx_db = np.round(Sxx_db, 1)

    return {
        "sample_rate": audio.sample_rate,
        "channel": channel,
        "times": times.tolist(),
        "freqs": freqs.tolist(),
        "magnitudes_db": Sxx_db.T.tolist(),  # Transpose for Plotly: rows=time, cols=freq
        "duration_s": audio.duration_s,
        "max_freq": float(freqs[-1]),
    }


@router.get("/waveform/{file_id}")
def get_waveform(
    file_id: str,
    channel: int = Query(0, ge=0, le=7),
    downsample: int = Query(8000, ge=100),
):
    """Get waveform data for visualization."""
    cached = _file_cache.get(file_id)
    if cached is None:
        raise HTTPException(404, "File not found. Re-upload the audio file.")

    audio, _ = cached

    if channel >= audio.channels:
        channel = 0

    signal = audio.samples[channel]
    n_samples = len(signal)

    # Downsample for display
    if n_samples > downsample:
        indices = np.linspace(0, n_samples - 1, downsample, dtype=int)
        signal = signal[indices]
        n_samples = downsample

    times = np.linspace(0, audio.duration_s, n_samples)

    return {
        "sample_rate": audio.sample_rate,
        "channel": channel,
        "times": times.tolist(),
        "samples": signal.tolist(),
        "duration_s": audio.duration_s,
        "channels": audio.channels,
    }
