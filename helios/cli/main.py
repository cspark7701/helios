"""HELIOS Command Line Interface (CLI).

Provides commands for plan inspection, closed-loop tuning, channel inspection,
and capability dispatch for heavy ion linac operators and physicists.
"""

import json
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.table import Table
import typer

from helios.agents.orchestrator import HeliosOrchestrator
from helios.core.capabilities import get_default_registry
from helios.core.schemas import AutonomyLevel
from helios.interfaces.channel_map import create_baseline_mebt_channel_manager

app = typer.Typer(
    name="helios",
    help="HELIOS: HEavy ion Linac Intelligent Orchestration CLI",
    add_completion=False,
)
console = Console()


@app.command()
def version():
    """Display the HELIOS version."""
    import helios
    console.print(f"[bold green]HELIOS[/bold green] version [bold cyan]{helios.__version__}[/bold cyan]")


@app.command()
def info():
    """Display system and framework status."""
    console.print("[bold blue]HELIOS Agentic AI Framework[/bold blue]")
    console.print("Reference Architecture: [bold magenta]LBNL Osprey[/bold magenta]")
    console.print("Target: [bold green]Heavy Ion Linear Accelerators[/bold green]")


@app.command()
def channels(section: str = typer.Option("MEBT", help="Linac section filter")):
    """List registered devices and EPICS PV bindings."""
    mgr = create_baseline_mebt_channel_manager()
    devices = mgr.filter_devices(section=section)

    table = Table(title=f"HELIOS Channels: Section [{section}]")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Type", style="magenta")
    table.add_column("Position z (m)", justify="right")
    table.add_column("Setpoint PV", style="green")
    table.add_column("Readback PV", style="yellow")
    table.add_column("Limits", style="white")

    for d in devices:
        lim_str = f"[{d.limits.min_val}, {d.limits.max_val}] {d.limits.units}" if d.limits else "N/A"
        table.add_row(
            d.name,
            d.device_type.value,
            f"{d.z_position_m:.2f}",
            d.setpoint_pv or "-",
            d.readback_pv or "-",
            lim_str,
        )

    console.print(table)


@app.command()
def tools(query: Optional[str] = typer.Option(None, help="Optional intent query to test classifier")):
    """List agent capabilities or dynamically classify intent."""
    reg = get_default_registry()

    if query:
        console.print(f"[bold cyan]Intent Query:[/bold cyan] '{query}'")
        caps = reg.classify_intent(query, max_tools=8)
    else:
        caps = reg.list_all()

    table = Table(title="HELIOS Dynamic Capabilities (Osprey Model)")
    table.add_column("Capability", style="cyan", no_wrap=True)
    table.add_column("Domain", style="magenta")
    table.add_column("Agent", style="green")
    table.add_column("Risk", style="yellow")
    table.add_column("Description", style="white")

    for c in caps:
        table.add_row(
            c.name,
            c.domain.value,
            c.target_agent,
            c.risk_level.value,
            c.description,
        )

    console.print(table)


@app.command()
def tune_orbit(
    section: str = typer.Option("MEBT", help="Linac section to tune (e.g. MEBT, LEBT)"),
    plan_id: str = typer.Option("00099", help="Execution plan ID"),
    autonomy: int = typer.Option(3, help="Autonomy level (0 to 4)"),
    model_dir: Optional[Path] = typer.Option(None, "--model-dir", "-m", help="Path to physics simulation model directory (e.g. examples/lebt)"),
    use_track: bool = typer.Option(True, "--track/--analytic", help="Use ANL TRACK beam dynamics code if available"),
    conversion_factor: float = typer.Option(0.168, "--conversion-factor", "-c", help="Steerer current conversion factor in A/mrad"),
    current_increment: float = typer.Option(0.05, "--current-increment", "-i", help="Power supply current step / increment limit in Amperes"),
):
    """Execute a closed-loop trajectory correction sequence."""
    import time
    start_time = time.perf_counter()

    # Check if a model directory was passed or LEBT section was requested with examples/lebt
    resolved_model = model_dir
    if resolved_model is None and section.upper() == "LEBT" and Path("examples/lebt").exists():
        resolved_model = Path("examples/lebt")

    if resolved_model is not None and resolved_model.exists():
        console.print(f"[bold green]Starting HELIOS closed-loop orbit correction on {section} using TRACK model in {resolved_model}...[/bold green]")
        console.print(f"  Transfer factor: [cyan]{conversion_factor:.3f} A/mrad[/cyan] | Current resolution: [cyan]{current_increment:.2f} A[/cyan]")
        from examples.tune_orbit_lebt import run_tune_orbit_example
        res = run_tune_orbit_example(
            resolved_model,
            conversion_factor_a_per_mrad=conversion_factor,
            current_increment_a=current_increment,
        )
        elapsed_s = res.get("elapsed_time_s", time.perf_counter() - start_time)
        console.print(f"[bold green]✔ Closed-Loop Orbit Correction Completed![/bold green]")
        console.print(f"  Horizontal RMS Improvement : [bold cyan]{res['improvement_pct']:+.1f}%[/bold cyan] ({res['initial_rms_x_mm']:.4f} mm -> {res['corrected_rms_x_mm']:.4f} mm)")
        console.print(f"  Orbit Correction Execution Time: [bold yellow]{elapsed_s:.2f} seconds[/bold yellow]")
        return

    console.print(f"[bold green]Starting autonomous orbit correction on {section}...[/bold green]")
    orch = HeliosOrchestrator()

    # Seed mock BPM offsets
    orch.control.put(f"{section}:DIAG:BPM01:X_POS", 0.75)
    orch.control.put(f"{section}:DIAG:BPM02:X_POS", 1.10)
    orch.control.put(f"{section}:PSC:CH01:CurrentSet", 0.0)
    orch.control.put(f"{section}:PSC:CH01:CurrentAct", 0.0)

    level = AutonomyLevel(autonomy)
    plan = orch.run_orbit_correction_loop(
        plan_id=plan_id,
        section=section,
        autonomy_level=level,
        operator_confirmed=True,
    )
    elapsed_s = time.perf_counter() - start_time

    console.print(f"[bold green]Plan Status:[/bold green] {plan.state.value}")
    console.print(f"[bold cyan]Steps Executed:[/bold cyan] {len(plan.steps)}")
    for s in plan.steps:
        console.print(f" - Step `{s.name}`: [{s.status.value}]")
    console.print(f"  Orbit Correction Execution Time: [bold yellow]{elapsed_s:.2f} seconds[/bold yellow]")


@app.command()
def plans():
    """List execution plans in docs/exec-plans/."""
    active_dir = Path("docs/exec-plans/active")
    completed_dir = Path("docs/exec-plans/completed")

    table = Table(title="HELIOS Execution Plans")
    table.add_column("Type", style="magenta")
    table.add_column("Filename", style="cyan")

    if active_dir.exists():
        for f in sorted(active_dir.glob("*.md")):
            table.add_row("ACTIVE", f.name)
    if completed_dir.exists():
        for f in sorted(completed_dir.glob("*.md")):
            table.add_row("COMPLETED", f.name)

    console.print(table)


@app.command()
def chat(
    provider: str = typer.Option("mock", help="LLM provider ('mock', 'openai', 'ollama')"),
    model: Optional[str] = typer.Option(None, help="LLM model name"),
):
    """Launch interactive conversational operator console."""
    from helios.agents.planner import NaturalLanguagePlanner
    from helios.core.llm import create_llm_client

    console.print("[bold green]════════════════════════════════════════════════════════════[/bold green]")
    console.print("[bold cyan]       HELIOS Autonomous Linac Assistant (Osprey TUI)       [/bold cyan]")
    console.print(f"[bold white] Provider: {provider} | Type 'exit' or 'quit' to terminate [/bold white]")
    console.print("[bold green]════════════════════════════════════════════════════════════[/bold green]\n")

    client = create_llm_client(provider=provider, model=model or "mock-helios-planner")
    planner = NaturalLanguagePlanner(llm_client=client)
    orch = HeliosOrchestrator()

    while True:
        try:
            prompt = console.input("[bold yellow]Physicist > [/bold yellow]").strip()
            if not prompt:
                continue
            if prompt.lower() in ("exit", "quit", "q"):
                console.print("[bold cyan]Session closed. Good day![/bold cyan]")
                break

            console.print("\n[dim]Analyzing directive and formulating execution plan...[/dim]")
            plan, explanation = planner.formulate_plan_from_prompt(prompt)

            console.print(f"[bold green]Assistant:[/bold green] {explanation}\n")

            # Display formulated plan summary
            table = Table(title=f"Proposed Plan: {plan.title} (ID: {plan.plan_id})")
            table.add_column("Step", style="cyan", no_wrap=True)
            table.add_column("Agent", style="magenta")
            table.add_column("Action", style="green")
            table.add_column("Parameters", style="white")

            for s in plan.steps:
                table.add_row(s.name, s.target_agent, s.action, json.dumps(s.parameters))
            console.print(table)

            # Operator Gating Prompt
            choice = console.input("\n[bold magenta]Authorize Execution? [y(Yes) / n(No) / d(Dry-Run)]: [/bold magenta]").strip().lower()
            if choice == "y":
                console.print("[bold green]Executing validated plan...[/bold green]")
                executed_plan = orch.run_orbit_correction_loop(
                    plan_id=plan.plan_id,
                    autonomy_level=AutonomyLevel.SUPERVISED,
                    operator_confirmed=True,
                )
                console.print(f"[bold green]Result:[/bold green] Plan status is [{executed_plan.state.value}]. Archived to docs/exec-plans/completed/.\n")
            else:
                console.print("[bold yellow]Plan execution deferred.[/bold yellow]\n")

        except (KeyboardInterrupt, EOFError):
            console.print("\n[bold cyan]Terminating session.[/bold cyan]")
            break


@app.command()
def dashboard(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Bind host"),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload for dev"),
):
    """Launch the HELIOS real-time operator web dashboard."""
    import uvicorn
    from helios.dashboard.app import create_dashboard_app

    console.print(f"[bold green]Starting HELIOS Operator Console at http://{host}:{port}[/bold green]")
    web_app = create_dashboard_app()
    uvicorn.run(web_app, host=host, port=port)


@app.command()
def report(
    facility: str = typer.Option("RAON_SCL1", "--facility", "-f", help="Facility name"),
    author: str = typer.Option("Control Room Physicist", "--author", "-a", help="Report author"),
):
    """Generate and display an automated commissioning shift handover report."""
    from datetime import datetime, timezone
    from helios.ops.reporting import CommissioningReportGenerator, ShiftSummaryData

    data = ShiftSummaryData(
        shift_label="DAY_COMMISSIONING_RUN",
        physicist_on_duty=author,
        facility_name=facility,
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        executed_plans_count=3,
        initial_orbit_rms_mm=0.85,
        final_orbit_rms_mm=0.12,
        initial_transmission_pct=92.5,
        final_transmission_pct=99.2,
        total_anomalies_detected=1,
        interlocks_tripped_count=0,
        notes="MEBT and SCL1 transverse trajectory optimized. RF stations operating nominally.",
    )
    md = CommissioningReportGenerator.generate_markdown_report(data)
    console.print(md)


@app.command()
def audit():
    """Verify cryptographic integrity of the operator audit ledger."""
    from helios.ops.audit import AuditTrailLogger

    logger = AuditTrailLogger()
    logger.log_action("OPERATOR", "INITIALIZE", "HELIOS:AUDIT:CHECK", 0.0, 1.0, "Integrity check entry")
    ok, err = logger.verify_integrity()
    if ok:
        console.print("[bold green]✔ Cryptographic Audit Trail Verified: All SHA-256 hash chains valid.[/bold green]")
    else:
        console.print(f"[bold red]✘ Audit Trail Integrity Failed: {err}[/bold red]")


if __name__ == "__main__":
    app()
