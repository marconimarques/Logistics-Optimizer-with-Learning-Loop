"""Pure Rich display layer — no business logic, no solver or Anthropic imports."""
from collections import defaultdict
from contextlib import contextmanager
from typing import Iterator

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

from src.models import SolverResult

console = Console()


def show_welcome() -> None:
    console.print()
    console.print(Panel.fit(
        "[bold cyan]LOGISTICS OPTIMIZER[/bold cyan]\n\n"
        "Powered by Claude + Pyomo/HiGHS MILP solver.\n"
        "Optimizes warehouse locations, zone assignments,\n"
        "and fleet sizing across 5 warehouses and 20 delivery zones.",
        border_style="cyan",
    ))
    console.print()


def show_model_info() -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="cyan")
    table.add_column()
    table.add_row("Model:", "claude-sonnet-4-6")
    table.add_row("Solver:", "Pyomo + HiGHS (MILP, in-process)")
    table.add_row("Network:", "5 warehouses · 20 delivery zones")
    console.print(table)
    console.print()


def prompt_user_message() -> str:
    return Prompt.ask(
        "[bold cyan]You[/bold cyan]"
    )


@contextmanager
def show_thinking() -> Iterator[Progress]:
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        yield progress


def show_solver_result(result: SolverResult, idx: int) -> None:
    out = result.output

    feasibility = (
        "[bold green]FEASIBLE[/bold green]"
        if out.is_feasible
        else "[bold red]INFEASIBLE[/bold red]"
    )

    # Header
    console.print(
        f"\n[bold cyan]Scenario {idx}: {result.scenario_name}[/bold cyan]  {feasibility}"
    )

    # Metrics table (no header)
    metrics = Table(show_header=False, box=None, padding=(0, 2))
    metrics.add_column(style="cyan")
    metrics.add_column()
    metrics.add_row("Total Cost:", f"€{out.total_cost:,.0f}")
    metrics.add_row("Avg Delivery Time:", f"{out.avg_delivery_time:.2f} hrs")
    metrics.add_row("Service Coverage:", f"{out.service_coverage:.0%}")
    console.print(metrics)

    if not out.is_feasible:
        console.print("[yellow]  No feasible solution found for these constraints.[/yellow]")
        console.print()
        return

    # Warehouse table
    console.print("\n[bold]Warehouse Status:[/bold]")
    wh_table = Table(show_header=True, box=None, padding=(0, 2))
    wh_table.add_column("Warehouse", style="cyan")
    wh_table.add_column("Status", justify="center")
    wh_table.add_column("Vehicles", justify="right")

    for wh, opened in out.warehouse_opening.items():
        status = "[green]OPEN[/green]" if opened else "[dim]closed[/dim]"
        vehicles = str(out.vehicle_allocation.get(wh, 0)) if opened else "-"
        wh_table.add_row(wh, status, vehicles)

    console.print(wh_table)

    # Zone assignments grouped by warehouse
    console.print("\n[bold]Zone Assignments:[/bold]")
    zone_table = Table(show_header=True, box=None, padding=(0, 2))
    zone_table.add_column("Warehouse", style="cyan")
    zone_table.add_column("Count", justify="right")
    zone_table.add_column("Zones")

    # Group zones by warehouse
    grouped: dict = defaultdict(list)
    for zone, warehouse in out.zone_assignments.items():
        if warehouse is not None:
            grouped[warehouse].append(zone)

    unserved = [z for z, w in out.zone_assignments.items() if w is None]

    for wh in sorted(grouped.keys()):
        zone_list = ", ".join(sorted(grouped[wh], key=lambda z: int(z.split("-")[1])))
        zone_table.add_row(wh, str(len(grouped[wh])), zone_list)

    if unserved:
        unserved_list = ", ".join(sorted(unserved, key=lambda z: int(z.split("-")[1])))
        zone_table.add_row("[dim]unserved[/dim]", str(len(unserved)), f"[dim]{unserved_list}[/dim]")

    console.print(zone_table)
    console.print()


def show_claude_response(text: str) -> None:
    if not text:
        return
    console.print(f"Answer: {text}")
    console.print()


def show_error(msg: str) -> None:
    console.print(f"\n[bold red]Error:[/bold red] {msg}\n")


def show_warning(msg: str) -> None:
    console.print(f"[yellow]{msg}[/yellow]")


def show_cancellation() -> None:
    console.print("\n[yellow]Interrupted. Goodbye![/yellow]\n")


def show_help() -> None:
    content = (
        "[bold]Available commands:[/bold]\n"
        "  [cyan]help[/cyan]   — Show this message\n"
        "  [cyan]clear[/cyan]  — Reset conversation history\n"
        "  [cyan]quit[/cyan]   — Exit\n\n"
        "[bold]Example queries:[/bold]\n\n"
        "[dim]Simple optimization:[/dim]\n"
        '  "Minimize total cost"\n'
        '  "Fastest delivery network"\n'
        '  "Maximize service coverage"\n'
        '  "Minimize fleet size"\n\n'
        "[dim]Comparative analysis:[/dim]\n"
        '  "Compare cost vs delivery time"\n'
        '  "Show trade-off between cost and coverage"\n\n'
        "[dim]Constrained optimization:[/dim]\n"
        '  "Minimize cost with max 2-hour delivery and 80% coverage"\n'
        '  "Serve all zones with max 1 vehicle per warehouse"\n'
        '  "Best coverage within a 1.5-hour delivery limit"'
    )
    console.print(Panel.fit(content, title="[bold green]Help[/bold green]", border_style="green"))
    console.print()


def confirm_clear_history() -> bool:
    return Confirm.ask("[yellow]Clear conversation history?[/yellow]", default=False)


def prompt_session_rating() -> int | None:
    """
    Ask the user for a session-level usefulness rating at exit.

    Returns 1, 2, or 3 on valid input; None if the user presses Enter or provides
    anything else. Never raises.
    """
    try:
        raw = Prompt.ask(
            "\n[dim]How useful was this session? "
            "[1=not useful / 2=ok / 3=very useful] (Enter to skip)[/dim]",
            default="",
        ).strip()
        if raw in {"1", "2", "3"}:
            return int(raw)
    except Exception:
        pass
    return None
