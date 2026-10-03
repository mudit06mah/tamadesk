"""`tamadesk` command line: serve the desk, check the setup, open it in a browser."""

from __future__ import annotations

import webbrowser

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


if __name__ == "__main__":
    app()
