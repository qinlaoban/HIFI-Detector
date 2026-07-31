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
from .core.library import scan_library
from .core.hires import verify_hires

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
                "peak_rms_per_channel_dbfs": dr.peak_rms_per_channel,
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


_GRADE_STYLE = {
    "A+": "bold green",
    "A": "green",
    "B": "yellow",
    "C": "yellow",
    "D": "red",
    "E": "bold red",
}


def _album_table(albums, title: str, border: str) -> Table:
    """Render a list of albums as a rich table."""
    table = Table(title=title, border_style=border)
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("专辑", style="bold", max_width=34, overflow="ellipsis")
    table.add_column("等级", justify="center", width=6)
    table.add_column("DR", justify="center", width=5)
    table.add_column("LUFS", justify="right", width=7)
    table.add_column("曲", justify="right", width=4)
    table.add_column("结论", max_width=34, overflow="ellipsis")
    for i, a in enumerate(albums, 1):
        style = _GRADE_STYLE.get(a.grade, "white")
        dr_range = f"{a.dr_median}" if a.dr_min == a.dr_max else f"{a.dr_min}-{a.dr_max}"
        table.add_row(
            str(i),
            a.name,
            f"[{style}]{a.grade}[/{style}]",
            dr_range,
            f"{a.lufs_median:.1f}",
            str(a.n_tracks),
            a.verdict,
        )
    return table


@app.command()
def scan(
    directory: str = typer.Argument(..., help="Music library root directory"),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive", "-r", help="Scan subdirectories"),
    top: int = typer.Option(10, "--top", "-n", help="How many albums to show in each ranking"),
    show_all: bool = typer.Option(False, "--all", "-a", help="List every album"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save JSON report to file"),
):
    """Scan a music library: grade every album and report the loudness war."""
    from dataclasses import asdict
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

    path = Path(directory)
    if not path.is_dir():
        console.print(f"[red]Not a directory:[/red] {directory}")
        raise typer.Exit(1)

    # Scan with a progress bar.
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as prog:
        task_id = prog.add_task("Scanning", total=None)

        def _progress(i: int, total: int, name: str):
            prog.update(task_id, total=total, completed=i, description=f"[cyan]{name[:40]}")

        report = scan_library(path, recursive=recursive, progress=_progress)

    if report.n_albums == 0:
        console.print("[yellow]No audio files found.[/yellow]")
        return

    # --- JSON output ---
    if json_output or output:
        payload = {
            "root": report.root,
            "n_files": report.n_files,
            "n_errors": report.n_errors,
            "n_albums": report.n_albums,
            "avg_dr": report.avg_dr,
            "pct_crushed": report.pct_crushed,
            "grade_distribution": report.grade_distribution,
            "albums": [asdict(a) for a in report.albums],
        }
        json_str = json.dumps(payload, indent=2, ensure_ascii=False)
        if output:
            Path(output).write_text(json_str)
            console.print(f"[dim]Report saved to {output}[/dim]")
        if json_output:
            console.print(json_str)
            return  # JSON on stdout: don't also emit the rich tables

    # --- Rich report ---
    # Overview panel
    overview = Table.grid(padding=(0, 2))
    overview.add_column(style="bold cyan")
    overview.add_column()
    overview.add_row("Library:", report.root)
    overview.add_row("Files:", f"{report.n_files} tracks in {report.n_albums} albums"
                     + (f" ({report.n_errors} errors)" if report.n_errors else ""))
    overview.add_row("Average DR:", f"{report.avg_dr}")
    crushed_style = "red" if report.pct_crushed > 30 else ("yellow" if report.pct_crushed > 0 else "green")
    overview.add_row("Loudness war:",
                     f"[{crushed_style}]{report.pct_crushed}% of albums look crushed (DR≤7)[/{crushed_style}]")

    # Grade distribution
    dist_parts = []
    for g in ["A+", "A", "B", "C", "D", "E"]:
        count = report.grade_distribution.get(g, 0)
        if count:
            style = _GRADE_STYLE.get(g, "white")
            dist_parts.append(f"[{style}]{g}:{count}[/{style}]")
    overview.add_row("Grades:", "  ".join(dist_parts) if dist_parts else "-")
    console.print(Panel(overview, title="[bold]Library Report Card[/bold]", border_style="blue"))
    console.print()

    # Loudness war report (worst first)
    worst = [a for a in report.albums if a.loudness_war][:top]
    if worst:
        console.print(_album_table(
            worst,
            f"🔥 Loudness War Report — {len(worst)} most crushed albums",
            "red",
        ))
        console.print()

    # Best dynamics
    best = sorted(report.albums, key=lambda a: (-a.dr_median, a.lufs_median))[:top]
    console.print(_album_table(best, f"✅ Best Dynamics — Top {len(best)}", "green"))
    console.print()

    if show_all:
        console.print(_album_table(report.albums, "All Albums (worst → best)", "dim"))
        console.print()


_VERDICT_STYLE = {
    "genuine_hires": "bold green",
    "fake_hires": "bold red",
    "suspicious": "bold yellow",
    "not_hires": "dim",
}


def _print_hires_panel(path: str, rep) -> None:
    """Render a focused hi-res verdict for one file."""
    style = _VERDICT_STYLE.get(rep.verdict, "white")
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold cyan")
    grid.add_column()
    grid.add_row("文件:", Path(path).name)
    grid.add_row("声称规格:", rep.hires_target)
    grid.add_row("判定:", f"[{style}]{rep.verdict_label}[/{style}]  (置信度 {rep.confidence:.2f})")
    grid.add_row("结论:", rep.summary)
    console.print(Panel(grid, title="[bold]Hi-Res 真假判定[/bold]", border_style=rep.verdict_color))

    if rep.issues:
        console.print("[bold]证据：[/bold]")
        for issue in rep.issues:
            console.print(f"  [red]●[/red] [bold]{issue.headline}[/bold] [dim](置信度 {issue.confidence:.2f})[/dim]")
            console.print(f"    [dim]{issue.detail}[/dim]")
        console.print()


@app.command()
def verify(
    path: str = typer.Argument(..., help="Audio file or directory of 'hi-res' files"),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive", "-r", help="Scan subdirectories"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Verify whether file(s) are genuine hi-res — the focused authenticity check."""
    from dataclasses import asdict
    from .core.library import iter_audio_files

    target = Path(path)
    if not target.exists():
        console.print(f"[red]Path not found:[/red] {path}")
        raise typer.Exit(1)

    # Collect files (single file or directory).
    if target.is_file():
        files = [target]
    else:
        files = iter_audio_files(target, recursive=recursive)
        if not files:
            console.print("[yellow]No audio files found.[/yellow]")
            return

    reports = []
    for f in files:
        try:
            audio = read_audio(f)
            reports.append((f, verify_hires(audio)))
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]ERROR[/red] {f.name} — {e}")

    if not reports:
        return

    # --- JSON output ---
    if json_output:
        payload = [
            {"file": str(f), "hires": asdict(rep)} for f, rep in reports
        ]
        console.print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    # --- Single file: detailed panel ---
    if len(reports) == 1:
        f, rep = reports[0]
        _print_hires_panel(str(f), rep)
        return

    # --- Directory: verdict table + summary ---
    table = Table(title=f"Hi-Res Verification — {len(reports)} files", border_style="blue")
    table.add_column("文件", style="bold", max_width=40, overflow="ellipsis")
    table.add_column("声称规格", width=16)
    table.add_column("判定", justify="center", width=12)
    table.add_column("结论", max_width=44, overflow="ellipsis")

    counts = {"genuine_hires": 0, "fake_hires": 0, "suspicious": 0, "not_hires": 0}
    for f, rep in reports:
        counts[rep.verdict] = counts.get(rep.verdict, 0) + 1
        style = _VERDICT_STYLE.get(rep.verdict, "white")
        table.add_row(
            f.name,
            rep.hires_target,
            f"[{style}]{rep.verdict_label}[/{style}]",
            rep.summary,
        )
    console.print(table)
    console.print()

    # Summary line — the "how many fakes" headline.
    claimed = sum(1 for _, r in reports if r.claims_hires)
    fake = counts["fake_hires"]
    susp = counts["suspicious"]
    fake_rate = (fake / claimed * 100) if claimed else 0.0
    summary = Text()
    summary.append(f"真 Hi-Res: ", style="bold")
    summary.append(f"{counts['genuine_hires']}  ", style="green")
    summary.append(f"假 Hi-Res: ", style="bold")
    summary.append(f"{fake}  ", style="red")
    summary.append(f"可疑: ", style="bold")
    summary.append(f"{susp}  ", style="yellow")
    summary.append(f"非 Hi-Res: ", style="bold")
    summary.append(f"{counts['not_hires']}  ", style="dim")
    if claimed:
        summary.append(f"| 声称 hi-res 中假货率: {fake_rate:.0f}%", style="bold red" if fake_rate > 0 else "green")
    console.print(Panel(summary, title="[bold]Summary[/bold]"))


def main():
    app()


if __name__ == "__main__":
    app()
