"""`tamadesk` command line: serve the desk, check the setup, open it, move your data to another
computer (export/import), and start at login."""

from __future__ import annotations

import sqlite3
import subprocess
import tempfile
import webbrowser
import zipfile
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from tamadesk.core import db
from tamadesk.core.config import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def serve(reload: bool = typer.Option(False, help="auto-reload on code changes (dev)")) -> None:
    """Run the desk (API + UI + reminders) on 127.0.0.1:6206."""
    import uvicorn

    s = get_settings()
    uvicorn.run("tamadesk.api.app:create_app", factory=True, host=s.server.host, port=s.server.port,
                reload=reload, log_level="info")  # fmt: skip


@app.command()
def doctor() -> None:
    """Check the brain, the data folder and the database."""
    from tamadesk.brain import get_brain

    s = get_settings()
    conn = db.connect(s.db_path)
    version = db.migrate(conn)
    conn.close()
    ok, detail = get_brain(s).check()
    typer.echo(f"{'ok ' if ok else 'FAIL'}  brain     {detail}")
    from tamadesk.modules import sources, spec

    reach = sources.agent_reach_ready()
    typer.echo(f"{'ok ' if reach else 'warn'}  web       " + ("agent-reach (Exa search) ready" if reach else
               "agent-reach not found: web search tabs (Leads, Web watch) need `pipx install agent-reach`"))  # fmt: skip
    typer.echo(f"ok    tabs      {len(spec.load_all(s))} module(s) in {spec.module_dir(s)}")
    typer.echo(f"ok    data      {s.home}")
    typer.echo(f"ok    database  schema v{version}")
    raise typer.Exit(0 if ok else 1)


@app.command("open")
def open_desk() -> None:
    """Open the desk in your browser."""
    s = get_settings()
    webbrowser.open(f"http://{s.server.host}:{s.server.port}")


def _today() -> date:
    from tamadesk.life.today import local_today

    return local_today()


SKIP = ("secrets.json",)  # app passwords and calendar addresses never leave this computer in an export


@app.command("export")
def export_data(
    path: Annotated[Path | None, typer.Argument(help="zip to write (default: tamadesk-DATE.zip)")] = None,
) -> None:
    """Pack your desk (database, settings, tabs, memory) into one zip, without your secrets."""
    s = get_settings()
    path = path or Path(f"tamadesk-{_today().isoformat()}.zip")
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        snap = Path(tmp) / "tamadesk.db"
        src, dst = sqlite3.connect(s.db_path), sqlite3.connect(snap)
        src.backup(dst)  # a consistent copy even while the desk is running
        src.close(), dst.close()
        z.write(snap, "tamadesk.db")
        for f in s.home.rglob("*"):
            # not secrets, not the live database (the snapshot above), and never a zip (or this one)
            if (
                f.is_file()
                and f.name not in SKIP
                and not f.name.startswith("tamadesk")
                and f.suffix != ".zip"
            ):
                z.write(f, str(f.relative_to(s.home)))
    typer.echo(f"exported to {path} (secrets.json left out: set up mail and calendar again after importing)")


@app.command("import")
def import_data(
    path: Path, force: bool = typer.Option(False, help="replace a desk that already has data")
) -> None:
    """Unpack an export into this computer's data folder. Stop the desk first."""
    s = get_settings()
    if s.db_path.exists() and s.db_path.stat().st_size > 0 and not force:
        typer.echo(f"{s.home} already has a desk. Use --force to replace it (the old database is kept as "
                   "tamadesk.before-import.db).")  # fmt: skip
        raise typer.Exit(1)
    if s.db_path.exists():
        s.db_path.replace(s.home / "tamadesk.before-import.db")
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():  # never write outside the data folder
            target = (s.home / name).resolve()
            if s.home.resolve() not in target.parents and target != s.home.resolve():
                raise typer.BadParameter(f"refusing {name}: it points outside the data folder")
        z.extractall(s.home)
    typer.echo(f"imported into {s.home}. Start it with `tamadesk serve`.")


@app.command("install-service")
def install_service(dry_run: bool = typer.Option(False, help="only show what it would do")) -> None:
    """Start tamadesk at login (Linux systemd, macOS launch agent, Windows Startup folder)."""
    from tamadesk.core import service

    f, text, commands = service.plan()
    typer.echo(f"would write {f}" if dry_run else f"writing {f}")
    if dry_run:
        typer.echo(text)
        for c in commands:
            typer.echo("would run: " + " ".join(c))
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    for c in commands:
        subprocess.run(c, check=False)
    typer.echo("done: tamadesk starts at login now (and is starting now on Linux and macOS).")


if __name__ == "__main__":
    app()
