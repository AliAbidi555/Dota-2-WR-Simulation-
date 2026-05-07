"""
CLI helper for the Dota 2 Tracker.

Usage:
    python cli.py serve              # start the API server
    python cli.py add <account_id>   # add a friend
    python cli.py remove <account_id>
    python cli.py list               # list tracked friends
"""

import asyncio
import json
import typer
import uvicorn
from pathlib import Path
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Dota 2 Performance Tracker CLI")
console = Console()

FRIENDS_FILE = Path(__file__).parent / "friends.json"


def _load_friends() -> dict:
    if not FRIENDS_FILE.exists():
        return {"friends": []}
    with open(FRIENDS_FILE) as f:
        return json.load(f)


def _save_friends(data: dict) -> None:
    with open(FRIENDS_FILE, "w") as f:
        json.dump(data, f, indent=2)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes"),
):
    """Start the FastAPI server."""
    console.print(f"[bold green]Starting Dota 2 Tracker API[/bold green] at http://{host}:{port}")
    console.print(f"  → Swagger UI: [cyan]http://{host}:{port}/docs[/cyan]")
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


@app.command()
def add(
    account_id: int = typer.Argument(..., help="Steam account ID (32-bit)"),
    label: str = typer.Option(None, "--label", "-l", help="Optional nickname"),
):
    """Add a friend to the tracking list."""
    data = _load_friends()
    ids = [f["account_id"] for f in data["friends"]]
    if account_id in ids:
        console.print(f"[yellow]Already tracking {account_id}[/yellow]")
        raise typer.Exit(1)
    data["friends"].append({"account_id": account_id, "label": label})
    _save_friends(data)
    label_str = f" ({label})" if label else ""
    console.print(f"[green]✓ Added {account_id}{label_str}[/green]")


@app.command()
def remove(
    account_id: int = typer.Argument(..., help="Steam account ID to remove"),
):
    """Remove a friend from the tracking list."""
    data = _load_friends()
    before = len(data["friends"])
    data["friends"] = [f for f in data["friends"] if f["account_id"] != account_id]
    if len(data["friends"]) == before:
        console.print(f"[red]Not found: {account_id}[/red]")
        raise typer.Exit(1)
    _save_friends(data)
    console.print(f"[green]✓ Removed {account_id}[/green]")


@app.command(name="list")
def list_friends():
    """List all tracked friends."""
    data = _load_friends()
    friends = data.get("friends", [])
    if not friends:
        console.print("[yellow]No friends tracked yet. Use [bold]add[/bold] to add one.[/yellow]")
        return

    table = Table(title="Tracked Friends")
    table.add_column("Account ID", style="cyan")
    table.add_column("Label", style="magenta")
    for f in friends:
        table.add_row(str(f["account_id"]), f.get("label") or "—")
    console.print(table)


@app.command(name="refresh-matches")
def refresh_matches(
    force: bool = typer.Option(False, "--force", help="Re-fetch match ID lists even if cached"),
    limit: int  = typer.Option(200,   "--limit", help="Number of recent matches per player"),
):
    """
    Fetch and cache full match data for the last N matches of each tracked player.

    Saves to data/match_cache/:
      player_match_ids/{account_id}.json  — ordered match list per player
      matches/{match_id}.json             — full match JSON per match

    Match files are permanent — they are never re-fetched once saved.
    Re-running is safe and fast (only missing matches are fetched).
    Use --force to refresh the per-player match ID lists.
    """
    from app.match_cache import collect_match_history, cache_stats

    data        = _load_friends()
    account_ids = [f["account_id"] for f in data["friends"]]

    before = cache_stats()
    console.print(f"[bold cyan]Dota 2 Tracker — Match History Refresh[/bold cyan]")
    console.print(f"  Players : {len(account_ids)}")
    console.print(f"  Limit   : {limit} matches each")
    console.print(f"  Cache   : {before['matches']} matches already stored\n")

    asyncio.run(collect_match_history(account_ids, limit=limit, force=force))

    after = cache_stats()
    console.print(f"\n[bold green]✓ Done[/bold green]  ({after['matches']} matches in cache)")


@app.command(name="refresh-data")
def refresh_data(
    force: bool = typer.Option(False, "--force", help="Re-fetch even if cache is fresh"),
):
    """
    Fetch and cache enriched stats for the win probability model.

    Saves to data/:
      player_role_stats.json  — per-player winrate in each role + hero breakdown
      hero_matchups.json      — head-to-head matchup rates for tracked heroes
      hero_global_stats.json  — global per-position pick/win counts (/heroStats)

    Skips datasets that are < 6 hours old unless --force is passed.
    """
    from app.collector import collect_all

    console.print("[bold cyan]Dota 2 Tracker — Data Refresh[/bold cyan]")
    asyncio.run(collect_all(force=force))
    console.print("[bold green]✓ Done[/bold green]")


if __name__ == "__main__":
    app()
