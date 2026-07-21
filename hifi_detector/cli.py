"""HIFI Detector CLI — analyze audio quality and authenticity."""

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .core.audio_io import read_audio
from .core.metadata import extract_metadata
from .core.quality import analyze_quality
from .core.loudness import analyze_loudness
from .core.dynamic_range import analyze_dynamic_range
from .core.authenticity import analyze_authenticity

app = typer.Typer(
    name="hifi-detect",
    help="HIFI Audio Quality Detector — analyze audio files for quality and authenticity.",
)
console = Console()


def _bar(value: float, vmin: float, vmax: float, width: int = 12) -> str:
    """Draw a mini bar chart."""
    filled = int(max(0, min(width, (value - vmin) / (vmax - vmin) * width)))
    if filled < 0:
        filled = 0
    return "█" * filled + "░" * (width - filled)


@app.command()
def analyze(
    file: str = typer.Argument(..., help="Audio file to analyze"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
):
    """Analyze a single audio file."""
    audio = None
    try:
        audio = read_audio(file)
    except FileNotFoundError:
        console.print(f"[red]File not found:[/red] {file}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Failed to read file:[/red] {e}")
        raise typer.Exit(1)

    meta = extract_metadata(audio)
    quality = analyze_quality(audio)
    loudness = analyze_loudness(audio)
    dr = analyze_dynamic_range(audio)
    authenticity = analyze_authenticity(audio)

    if json_output:
        result = {
            "file": str(audio.file_path),
            "metadata": {
                "format": meta.format,
                "subtype": meta.subtype,
                "sample_rate": meta.sample_rate,
                "bit_depth": meta.bit_depth,
                "channels": meta.channels,
                "duration_s": round(meta.duration_s, 2),
                "file_size_mb": meta.file_size_mb,
                "bitrate_kbps": meta.bitrate_kbps,
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
                "top20_rms_per_channel_dbfs": dr.top20_rms_per_channel,
                "overall_rms_per_channel_dbfs": dr.overall_rms_per_channel,
                "boundary_risk": dr.boundary_risk,
            },
            "authenticity": {
                "is_suspicious": authenticity.is_suspicious,
                "overall_confidence": authenticity.overall_confidence,
                "cutoff_freq_hz": authenticity.cutoff_freq_hz,
                "cutoff_suspected_codec": authenticity.cutoff_suspected_codec,
                "has_sharp_cutoff": authenticity.has_sharp_cutoff,
                "cutoff_confidence": authenticity.cutoff_confidence,
                "is_suspected_upsampled": authenticity.is_suspected_upsampled,
                "hf_energy_ratio": authenticity.hf_energy_ratio,
                "hf_energy_db": authenticity.hf_energy_db,
                "upsample_source_rate_hint": authenticity.upsample_source_rate_hint,
                "low_bits_active": authenticity.low_bits_active,
                "fake_24bit_confidence": authenticity.fake_24bit_confidence,
                "suspicion_reasons": authenticity.suspicion_reasons,
            },
        }
        console.print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # --- Rich terminal output ---
    _print_report(audio, meta, quality, loudness, dr, authenticity, quiet)


def _print_report(audio, meta, quality, loudness, dr, authenticity, quiet: bool):
    """Print a rich terminal report."""
    # Verdicts
    issues = []

    # Clipping
    if quality.clip_samples > 0:
        issues.append(("CLIPPING", "red"))
    else:
        issues.append(("CLIPPING", "green"))

    # DC offset
    if quality.dc_offset_pct > 0.1:
        issues.append(("DC OFFSET", "yellow"))
    else:
        issues.append(("DC OFFSET", "green"))

    # Channel balance
    if quality.balance_diff_db > 1.0:
        issues.append(("BALANCE", "yellow"))
    else:
        issues.append(("BALANCE", "green"))

    # True Peak
    tp_max = loudness.true_peak_db_l
    if loudness.true_peak_db_r is not None:
        tp_max = max(tp_max, loudness.true_peak_db_r)
    if tp_max > -0.1:
        issues.append(("PEAK", "red"))
    elif tp_max > -1.0:
        issues.append(("PEAK", "yellow"))
    else:
        issues.append(("PEAK", "green"))

    # Dynamic Range
    if dr.dr_official >= 14:
        issues.append(("DR", "green"))
    elif dr.dr_official >= 10:
        issues.append(("DR", "yellow"))
    else:
        issues.append(("DR", "red"))

    # Bit depth
    if quality.bit_depth_suspicious:
        issues.append(("BIT DEPTH", "yellow"))
    else:
        issues.append(("BIT DEPTH", "green"))

    # Authenticity
    if authenticity.is_suspicious:
        auth_style = "red" if authenticity.overall_confidence > 0.6 else "yellow"
        issues.append(("AUTHENTICITY", auth_style))
    else:
        issues.append(("AUTHENTICITY", "green"))

    # Overall
    red_count = sum(1 for _, style in issues if style == "red")
    yellow_count = sum(1 for _, style in issues if style == "yellow")

    if red_count > 0:
        verdict = "ISSUES DETECTED"
        verdict_style = "red"
    elif yellow_count > 0:
        verdict = "MINOR ISSUES"
        verdict_style = "yellow"
    else:
        if dr.dr_official >= 14:
            verdict = "HIGH QUALITY"
            verdict_style = "green"
        else:
            verdict = "CLEAN"
            verdict_style = "green"

    # Build report
    if not quiet:
        # Header
        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold cyan")
        header.add_column()
        header.add_row("File:", meta.file_path)
        header.add_row("Format:", f"{meta.format} | {meta.subtype} | {meta.sample_rate/1000:.1f} kHz | {meta.bit_depth} bit | {meta.channels}ch")
        header.add_row("Duration:", f"{meta.duration_display} | {meta.file_size_mb:.1f} MB | {meta.bitrate_kbps or 'N/A'} kbps")
        console.print(Panel(header, title="[bold]Audio Info[/bold]", border_style="blue"))
        console.print()

        # Quality table
        qtable = Table(title="Quality Analysis", border_style="dim")
        qtable.add_column("Metric", style="bold", width=18)
        qtable.add_column("Value", width=28)
        qtable.add_column("Graph", width=14)
        qtable.add_column("Verdict", width=20)

        # Clipping
        clip_text = f"{quality.clip_samples} samples ({quality.clip_ratio_pct:.3f}%)"
        if quality.clip_samples == 0:
            qtable.add_row("Clipping", clip_text, _bar(0, 0, 1), "[green]CLEAN[/green]")
        else:
            qtable.add_row("Clipping", clip_text, _bar(quality.clip_ratio_pct, 0, 0.01),
                          f"[red]{quality.clip_samples} CLIPS[/red]")

        # DC Offset
        dc_text = f"{quality.dc_offset_pct:.4f}%"
        dc_v = "CLEAN" if quality.dc_offset_pct <= 0.1 else "ISSUE"
        dc_s = "green" if quality.dc_offset_pct <= 0.1 else "yellow"
        qtable.add_row("DC Offset", dc_text,
                      _bar(quality.dc_offset_pct, 0, 0.5),
                      f"[{dc_s}]{dc_v}[/{dc_s}]")

        # Channel Balance
        bal_text = f"{quality.balance_diff_db:.2f} dB"
        bal_v = "CLEAN" if quality.balance_diff_db <= 1.0 else "ISSUE"
        bal_s = "green" if quality.balance_diff_db <= 1.0 else "yellow"
        qtable.add_row("Channel Balance", bal_text,
                      _bar(quality.balance_diff_db, 0, 3),
                      f"[{bal_s}]{bal_v}[/{bal_s}]")

        # True Peak
        tp_text = f"L:{loudness.true_peak_db_l:.2f}"
        if loudness.true_peak_db_r is not None:
            tp_text += f" R:{loudness.true_peak_db_r:.2f}"
        tp_display = max(loudness.true_peak_db_l, loudness.true_peak_db_r or -999)
        if tp_display > -0.1:
            tp_v, tp_s = "CLIPPING", "red"
        elif tp_display > -1.0:
            tp_v, tp_s = "WARN", "yellow"
        else:
            tp_v, tp_s = "OK", "green"
        qtable.add_row("True Peak", f"{tp_text} dBTP",
                      _bar(tp_display + 6, -6, 0, 12),
                      f"[{tp_s}]{tp_v}[/{tp_s}]")

        # Dynamic Range
        dr_ch = f"DR{dr.dr_official}"
        if dr.dr_precise_avg_db > 0:
            dr_ch += f" ({dr.dr_precise_avg_db:.1f} dB)"
        dr_v, dr_s = dr.rating, dr.rating_color
        dr_bar = _bar(dr.dr_official if dr.dr_official <= 20 else 20, 0, 20, 12)
        dr_detail = ""
        if dr.boundary_risk:
            dr_detail = f" ⚠ boundary"
        qtable.add_row("Dynamic Range", f"{dr_ch}{dr_detail}",
                      dr_bar,
                      f"[{dr_s}]{dr_v}[/{dr_s}]")

        # RMS
        rms_text = f"L:{loudness.rms_db_l:.1f}"
        if loudness.rms_db_r is not None:
            rms_text += f" R:{loudness.rms_db_r:.1f}"
        qtable.add_row("RMS Level", f"{rms_text} dBFS", "", "[dim]INFO[/dim]")

        # Integrated LUFS
        qtable.add_row("Integrated LUFS", f"{loudness.integrated_lufs:.1f} LUFS", "", "[dim]INFO[/dim]")

        # Loudness Range
        qtable.add_row("Loudness Range", f"{loudness.loudness_range_lu:.1f} LU", "", "[dim]INFO[/dim]")

        # Bit depth
        if quality.bit_depth_suspicious:
            bd_text = f"[yellow]Reported: {audio.bit_depth}bit, Effective: {quality.effective_bits}bit[/yellow]"
            bd_v, bd_s = "SUSPICIOUS", "yellow"
        else:
            bd_text = f"{audio.bit_depth} bit"
            bd_v, bd_s = "OK", "green"
        qtable.add_row("Bit Depth", bd_text, "", f"[{bd_s}]{bd_v}[/{bd_s}]")

        # --- Authenticity ---
        if authenticity.has_sharp_cutoff:
            cf_text = f"{authenticity.cutoff_freq_hz:.0f} Hz"
            cf_codec = authenticity.cutoff_suspected_codec or "Unknown"
            qtable.add_row("Spectral Cutoff",
                          f"[red]{cf_text} ({cf_codec})[/red]",
                          _bar(authenticity.cutoff_confidence, 0, 1, 12),
                          "[red]SUSPECT[/red]")
        else:
            qtable.add_row("Spectral Cutoff", "None detected", "", "[green]OK[/green]")

        if authenticity.is_suspected_upsampled:
            up_text = f"~{authenticity.upsample_source_rate_hint} Hz source"
            qtable.add_row("Upsampling", f"[red]{up_text}[/red]",
                          _bar(authenticity.overall_confidence, 0, 1, 12),
                          "[red]SUSPECT[/red]")
        else:
            qtable.add_row("Upsampling", "Not detected", "", "[green]OK[/green]")

        if not authenticity.low_bits_active and audio.bit_depth and audio.bit_depth >= 24:
            qtable.add_row("24-bit Authenticity",
                          "[yellow]Low bits inactive[/yellow]",
                          _bar(authenticity.fake_24bit_confidence, 0, 1, 12),
                          "[yellow]SUSPECT[/yellow]")
        elif not authenticity.low_bits_active:
            pass  # Only show for 24-bit files
        else:
            qtable.add_row("24-bit Authenticity", "Low bits active", "", "[green]OK[/green]")

        if authenticity.suspicion_reasons:
            reasons_text = "; ".join(authenticity.suspicion_reasons)
            qtable.add_row("Suspicion", f"[red]{reasons_text}[/red]", "", "[red]FLAGGED[/red]")

        console.print(qtable)
        console.print()

        # Final verdict
        vpanel = Panel(
            Text(verdict, style=f"bold {verdict_style}"),
            title="[bold]Overall Verdict[/bold]",
            border_style=verdict_style,
        )
        console.print(vpanel)
    else:
        # Quiet mode — just the verdict
        console.print(f"{verdict}: {meta.file_path}")


@app.command()
def batch(
    directory: str = typer.Argument(..., help="Directory containing audio files"),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Scan subdirectories"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save report to file"),
):
    """Batch analyze all audio files in a directory."""
    from pathlib import Path

    path = Path(directory)
    if not path.is_dir():
        console.print(f"[red]Not a directory:[/red] {directory}")
        raise typer.Exit(1)

    # Collect files
    pattern = "**/*" if recursive else "*"
    exts = {".flac", ".wav", ".mp3", ".aiff", ".aif", ".ogg", ".m4a", ".alac", ".ape"}
    files = [
        f for f in path.glob(pattern)
        if f.is_file() and f.suffix.lower() in exts
    ]

    if not files:
        console.print("[yellow]No audio files found.[/yellow]")
        return

    console.print(f"Found [cyan]{len(files)}[/cyan] audio files. Analyzing...")
    console.print()

    results = []
    for i, f in enumerate(files):
        try:
            audio = read_audio(f)
            meta = extract_metadata(audio)
            quality = analyze_quality(audio)
            loudness = analyze_loudness(audio)
            dr = analyze_dynamic_range(audio)
            authenticity = analyze_authenticity(audio)

            # Quick verdict
            clip = quality.clip_samples > 0
            dc = quality.dc_offset_pct > 0.1
            tp = max(loudness.true_peak_db_l, loudness.true_peak_db_r or -999) > -0.1
            dr_bad = dr.dr_official < 10
            auth_issue = authenticity.is_suspicious and authenticity.overall_confidence > 0.6

            if clip or tp or dr_bad or auth_issue:
                verdict = "[red]ISSUE[/red]"
            elif dc or authenticity.is_suspicious:
                verdict = "[yellow]WARN[/yellow]"
            else:
                verdict = "[green]OK[/green]"

            result = {
                "file": str(f.name),
                "path": str(f),
                "verdict": "ISSUE" if (clip or tp or dr_bad or auth_issue) else ("WARN" if (dc or authenticity.is_suspicious) else "OK"),
                "metadata": {
                    "format": meta.format,
                    "sample_rate": meta.sample_rate,
                    "bit_depth": meta.bit_depth,
                    "channels": meta.channels,
                    "duration_s": round(meta.duration_s, 2),
                },
                "quality": {
                    "clips": quality.clip_samples,
                    "dc_offset_pct": quality.dc_offset_pct,
                },
                "loudness": {
                    "integrated_lufs": loudness.integrated_lufs,
                },
                "dynamic_range": dr.dr_official,
                "authenticity": {
                    "is_suspicious": authenticity.is_suspicious,
                    "overall_confidence": authenticity.overall_confidence,
                },
            }
            results.append(result)

            console.print(f"[{i+1:>3}/{len(files)}] {verdict}  {f.name}")

        except Exception as e:
            console.print(f"[{i+1:>3}/{len(files)}] [red]ERROR[/red] {f.name} — {e}")

    # Summary
    ok_count = sum(1 for r in results if r["verdict"] == "OK")
    warn_count = sum(1 for r in results if r["verdict"] == "WARN")
    issue_count = sum(1 for r in results if r["verdict"] == "ISSUE")
    error_count = len(files) - len(results)

    console.print()
    summary = Text()
    summary.append(f"[green]OK: {ok_count}[/green]  ")
    summary.append(f"[yellow]WARN: {warn_count}[/yellow]  ")
    summary.append(f"[red]ISSUE: {issue_count}[/red]  ")
    summary.append(f"[dim]ERROR: {error_count}[/dim]")
    console.print(Panel(summary, title="Summary"))

    if json_output:
        json_str = json.dumps(results, indent=2, ensure_ascii=False)
        if output:
            Path(output).write_text(json_str)
            console.print(f"[dim]Report saved to {output}[/dim]")
        else:
            console.print()

    elif output:
        # Plain text report
        lines = [f"HIFI Detector Batch Report", f"Directory: {directory}", f"Files: {len(files)}", "", "Results:", ""]
        for r in results:
            lines.append(f"  [{r['verdict']}] {r['file']}")
            lines.append(f"    {r['metadata']['format']} {r['metadata']['sample_rate']}Hz {r['metadata']['bit_depth']}bit")
        Path(output).write_text("\n".join(lines))
        console.print(f"[dim]Report saved to {output}[/dim]")


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Bind address"),
    port: int = typer.Option(8099, "--port", "-p", help="Port number"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open browser on start"),
):
    """Launch the Web UI (interactive spectrogram and analysis dashboard)."""
    import webbrowser
    from .web.server import run as run_server

    url = f"http://{host}:{port}"
    console.print(f"[bold cyan]HIFI Detector Web UI[/bold cyan]")
    console.print(f"Starting server at [underline]{url}[/underline]")

    if open_browser:
        import threading

        def _open():
            import time

            time.sleep(1.5)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()

    run_server(host=host, port=port)


def main():
    app()


if __name__ == "__main__":
    app()
