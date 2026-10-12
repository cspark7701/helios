"""HELIOS CLI Entrypoint."""

import typer
from rich.console import Console

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


if __name__ == "__main__":
    app()
