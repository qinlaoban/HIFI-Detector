"""Focused Hi-Res authenticity verdict — the product's single sharp edge.

This module answers ONE question:

    "Is this file genuine hi-res, fake hi-res, or not hi-res at all?"

It builds on the low-level detectors in ``authenticity.py`` (upsampling,
spectral cutoff, fake bit-depth) and turns their raw signals into a clear,
honest verdict that a music lover can act on.

Honesty principle (also our brand):
    A "genuine" verdict means *no fake signatures were detected* — it is NOT
    a certification of provenance. Nobody can prove a file is the original
    studio master from the file alone. We catch fakes; we don't mint
    certificates. The wording below reflects that deliberately.

Verdict categories:
    genuine_hires  声称 hi-res 且通过全部检测（未发现问题）
    fake_hires     声称 hi-res 但检出高置信度造假（上采样/有损转码/假位深）
    suspicious     声称 hi-res，检出造假迹象但证据不够强，建议人工复核
    not_hires      实为 CD 或更低规格（未虚标；若含有损迹象会额外说明）
    undetermined   信号过弱（近乎静音），无有效内容可供分析
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .audio_io import AudioData
from .authenticity import AuthenticityReport, analyze_authenticity

# A file "claims hi-res" if it exceeds CD quality (16-bit / 44.1 kHz).
CD_SAMPLE_RATE = 44100
CD_BIT_DEPTH = 16

# Verdict thresholds on per-issue confidence (0-1).
FAKE_THRESHOLD = 0.70        # >= this  => definite fake
SUSPICIOUS_THRESHOLD = 0.40  # >= this  => suspicious

# Peak below which a file is treated as digital silence (≈ -120 dBFS). Such a
# file carries no analyzable content, so we decline to call it genuine or fake.
SILENCE_PEAK_THRESHOLD = 1e-6

# Confidence assigned when the (strict) upsampling detector fires.
UPSAMPLE_CONFIDENCE = 0.85
# Downgraded confidence for a weak upsampling hit (ambiguous grey zone).
UPSAMPLE_WEAK_CONFIDENCE = 0.51  # >= SUSPICIOUS_THRESHOLD, < FAKE_THRESHOLD

# What this detector can and cannot claim. Upsampling is only detectable when
# the resampler leaves a spectral brickwall at the source Nyquist; a high-quality
# polyphase resampler preserves the source band without a wall and is therefore
# indistinguishable from a genuinely dark recording (information-theoretic limit).
DETECTION_SCOPE = (
    "检测范围：留下频谱砖墙的上采样、有损转码、假位深。"
    "高质量重采样器（多相 FIR）把 CD 拉到 hi-res 时不留砖墙，"
    "与本身偏暗的合法录音在内容上无法区分——属信息论极限，无法识别。"
)


@dataclass
class HiResIssue:
    """A single detected problem, with human text + machine evidence."""

    kind: str            # "upsampled" | "lossy_transcode" | "fake_bitdepth"
    confidence: float    # 0.0 - 1.0
    headline: str        # short human line
    detail: str          # longer explanation
    evidence: dict = field(default_factory=dict)


@dataclass
class HiResReport:
    """Focused hi-res authenticity verdict."""

    # What the file claims
    claimed_sample_rate: int
    claimed_bit_depth: int
    claims_hires: bool
    hires_target: str            # e.g. "24-bit / 96 kHz"

    # The verdict
    verdict: str                 # genuine_hires | fake_hires | suspicious | not_hires | undetermined
    verdict_label: str           # 真 Hi-Res / 假 Hi-Res / 可疑 / 非 Hi-Res
    verdict_color: str           # green / red / yellow / dim
    summary: str                 # one-line honest conclusion
    confidence: float            # confidence in the verdict (0-1)

    # Evidence
    issues: list[HiResIssue] = field(default_factory=list)
    evidence_quality: str = "weak"     # "strong" | "weak"（genuine 时：正面证据强度）
    detection_scope: str = ""          # 可检测范围说明（无损重采样不可测）

    # Raw metrics (for a detail view / spectrogram)
    hf_energy_ratio: float = 0.0
    hf_energy_db: float = 0.0
    cutoff_freq_hz: float | None = None
    cutoff_codec: str | None = None
    low_bits_active: bool = True


# ---------------------------------------------------------------------------
# Pure logic (unit-testable without audio)
# ---------------------------------------------------------------------------

def claims_hires(sample_rate: int, bit_depth: int) -> bool:
    """True if the container claims more than CD quality."""
    return sample_rate > CD_SAMPLE_RATE or bit_depth > CD_BIT_DEPTH


def build_issues(auth: AuthenticityReport) -> list[HiResIssue]:
    """Translate raw authenticity signals into structured, explained issues."""
    issues: list[HiResIssue] = []

    # 1. Upsampling — strict detector, high confidence when it fires.
    if auth.is_suspected_upsampled:
        src = auth.upsample_source_rate_hint
        weak = auth.upsample_strength != "strong"
        issues.append(HiResIssue(
            kind="upsampled",
            confidence=UPSAMPLE_WEAK_CONFIDENCE if weak else UPSAMPLE_CONFIDENCE,
            headline=(
                f"疑似上采样：22.05 kHz 以上几乎无内容，可能从 {src} Hz 拉高"
                if weak
                else f"上采样：22.05 kHz 以上几乎无内容，疑似从 {src} Hz 拉高"
            ),
            detail=(
                f"高采样率容器中，CD 奈奎斯特频率（22.05 kHz）以上的能量占比仅 "
                f"{auth.hf_energy_ratio * 100:.4f}%（{auth.hf_energy_db:.1f} dB），"
                f"并在 22 kHz 附近呈砖墙式截断——这是 CD 源上采样到 hi-res 的典型特征。"
                + ("证据强度不足，建议人工复核。" if weak else "")
            ),
            evidence={
                "hf_energy_ratio": auth.hf_energy_ratio,
                "hf_energy_db": auth.hf_energy_db,
                "source_rate_hint": src,
                "strength": auth.upsample_strength,
            },
        ))

    # 2. Lossy transcode — spectral cutoff fingerprint.
    if auth.has_sharp_cutoff and auth.cutoff_freq_hz:
        codec = auth.cutoff_suspected_codec or "有损编码器"
        issues.append(HiResIssue(
            kind="lossy_transcode",
            confidence=auth.cutoff_confidence,
            headline=f"有损转码：~{auth.cutoff_freq_hz / 1000:.1f} kHz 频谱切顶（疑似 {codec}）",
            detail=(
                f"频谱在 {auth.cutoff_freq_hz:.0f} Hz 处出现陡峭截断"
                f"（{codec} 的低通指纹），说明源头是有损音频，被转封装进了无损容器。"
            ),
            evidence={
                "cutoff_freq_hz": auth.cutoff_freq_hz,
                "suspected_codec": auth.cutoff_suspected_codec,
                "cutoff_confidence": auth.cutoff_confidence,
            },
        ))

    # 3. Fake bit depth — 24-bit container with empty low bits.
    if not auth.low_bits_active:
        issues.append(HiResIssue(
            kind="fake_bitdepth",
            confidence=auth.fake_24bit_confidence,
            headline="假位深：低 8 位为空，疑似 16-bit 填充到 24-bit",
            detail=(
                "24-bit 样本的最低 8 位没有有效信息（残差近乎为零、网格对齐度极高），"
                "说明这是 16-bit 内容填充进 24-bit 容器，并非真正的高位深录音。"
            ),
            evidence={
                "fake_24bit_confidence": auth.fake_24bit_confidence,
                "low_bits_active": auth.low_bits_active,
            },
        ))

    issues.sort(key=lambda i: i.confidence, reverse=True)
    return issues


def derive_verdict(
    is_hires_claim: bool, issues: list[HiResIssue]
) -> tuple[str, str, str, str, float]:
    """Pure verdict logic.

    Returns:
        (verdict, verdict_label, verdict_color, summary, confidence)
    """
    max_conf = max((i.confidence for i in issues), default=0.0)

    if is_hires_claim:
        if max_conf >= FAKE_THRESHOLD:
            strong = [i for i in issues if i.confidence >= FAKE_THRESHOLD]
            summary = "判定为假 Hi-Res：" + "；".join(i.headline for i in strong)
            return "fake_hires", "假 Hi-Res", "red", summary, round(max_conf, 3)

        if issues and max_conf >= SUSPICIOUS_THRESHOLD:
            summary = "可疑，建议人工复核：" + "；".join(i.headline for i in issues)
            return "suspicious", "可疑", "yellow", summary, round(max_conf, 3)

        summary = "通过检测：未发现上采样、有损转码或假位深迹象"
        return "genuine_hires", "真 Hi-Res", "green", summary, round(1.0 - max_conf, 3)

    # Not claiming hi-res.
    lossy = [i for i in issues if i.kind == "lossy_transcode"]
    if lossy:
        summary = "非 Hi-Res（CD 或更低规格）；另检测到有损转码迹象"
    else:
        summary = "非 Hi-Res（CD 或更低规格），规格属实未虚标"
    confidence = round(max_conf, 3) if issues else 0.9
    return "not_hires", "非 Hi-Res", "dim", summary, confidence


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _format_target(sample_rate: int, bit_depth: int) -> str:
    bits = f"{bit_depth}-bit" if bit_depth else "?-bit"
    rate = f"{sample_rate / 1000:g} kHz" if sample_rate else "? kHz"
    return f"{bits} / {rate}"


def _positive_evidence(auth: AuthenticityReport) -> float:
    """Score (0-1) how strongly the file exhibits REAL hi-res characteristics.

    Unlike the negative checks (finding fake signatures), these are positive
    signs that the ultrasonic band contains genuine signal rather than the
    flat interpolation residue of an upsampled file.

    Returns:
        0.0 (no positive evidence) .. 1.0 (strong positive evidence)
    """
    score = 0.0
    if auth.hf_energy_db > -90:
        score += 0.4          # real ultrasonic content above a -90 dBFS floor
    if auth.hf_energy_ratio >= 0.001:
        score += 0.3          # at least 0.1% of total energy above 22.05 kHz
    if auth.hf_frame_consistency < 0.5:
        score += 0.3          # HF energy varies across frames (real dynamics)
    return min(1.0, score)


def verify_hires(audio: AudioData, auth: AuthenticityReport | None = None) -> HiResReport:
    """Produce the focused hi-res authenticity verdict for an audio file.

    Args:
        audio: decoded audio (from audio_io.read_audio).
        auth: optional pre-computed AuthenticityReport (avoids re-analysis).

    Returns:
        HiResReport with a clear genuine/fake/suspicious/not-hires verdict.
    """
    if auth is None:
        auth = analyze_authenticity(audio)

    sr = audio.sample_rate
    bits = audio.bit_depth
    is_claim = claims_hires(sr, bits)

    # Validity gate: digital silence / near-silence carries no analyzable content.
    # The honest answer is "undetermined", not "genuine" — absence of a fake
    # signature is meaningless when there is no signal to inspect.
    peak = float(abs(audio.samples).max()) if audio.samples.size else 0.0
    if peak < SILENCE_PEAK_THRESHOLD:
        return HiResReport(
            claimed_sample_rate=sr,
            claimed_bit_depth=bits,
            claims_hires=is_claim,
            hires_target=_format_target(sr, bits),
            verdict="undetermined",
            verdict_label="无法判定",
            verdict_color="dim",
            summary="信号过弱（近乎静音），无有效内容可供真伪分析",
            confidence=0.0,
            issues=[],
            evidence_quality="weak",
            detection_scope=DETECTION_SCOPE,
        )

    issues = build_issues(auth)
    verdict, label, color, summary, confidence = derive_verdict(is_claim, issues)

    # For a "genuine" pass, factor in positive evidence so the confidence and
    # wording reflect how much the file actually looks like a real hi-res master.
    evidence_quality = "weak"
    if verdict == "genuine_hires":
        positive = _positive_evidence(auth)
        # Cap below certainty: "genuine" means "no fake signature detected", not
        # a provenance certification (lossless upsampling is undetectable). Keep
        # mild differentiation by positive evidence, never claim high certainty.
        confidence = round(min(0.80, 0.6 + 0.2 * positive), 3)
        evidence_quality = "strong" if positive >= 0.5 else "weak"
        if evidence_quality == "strong":
            summary = "通过检测：未发现造假迹象，且存在真实高频内容与动态特征"

    return HiResReport(
        claimed_sample_rate=sr,
        claimed_bit_depth=bits,
        claims_hires=is_claim,
        hires_target=_format_target(sr, bits),
        verdict=verdict,
        verdict_label=label,
        verdict_color=color,
        summary=summary,
        confidence=confidence,
        issues=issues,
        evidence_quality=evidence_quality,
        detection_scope=DETECTION_SCOPE,
        hf_energy_ratio=auth.hf_energy_ratio,
        hf_energy_db=auth.hf_energy_db,
        cutoff_freq_hz=auth.cutoff_freq_hz,
        cutoff_codec=auth.cutoff_suspected_codec,
        low_bits_active=auth.low_bits_active,
    )
