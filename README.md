# tamadesk

A tiny pixel companion that lives on your desk and turns your day into an adventure.

Tell it what you did, what you need to do, and when to poke you. It keeps a daily log, tracks
your todos, rings your reminders, writes emails that actually sound like you, and recaps your day
every evening. Every finished thing earns XP. Your companion levels up with you.

tamadesk runs entirely on your own machine. There's no account, no server and no telemetry.
The writing is done by **your own** Claude Code (or a local model via Ollama).

> Status: early, playable alpha. Expect sharp edges and new companions.

## What it does

- **Quick capture**: one box for everything.
  - `bought groceries, finally fixed the bug` goes to your daily log.
  - `todo send the invoice` adds a todo.
  - `remind me to stretch in 20 min` or `remind me to call mom at 6pm` sets a reminder.
- **Todos** with XP, streaks and levels. Undoing a todo takes its XP back, so you can't farm it.
- **Reminders** ring in the app and as a desktop notification.
- **Your voice**: paste a few emails or essays you wrote. tamadesk studies them once, then drafts
  in your style without the corporate filler.
- **Evening recap**: your companion writes up your day and picks up to 3 small things for tomorrow.
- **New Game setup**: you answer a few questions about yourself, pick a companion, and you're in.

## Install

You need Python 3.12+, [uv](https://docs.astral.sh/uv/) and Node 20+ (Node is only needed to
build the UI).

```sh
git clone https://github.com/mudit06mah/tamadesk && cd tamadesk
uv sync
cd frontend && npm install && npm run build && cd ..
uv run tamadesk doctor     # checks your brain (Claude Code or Ollama)
uv run tamadesk serve      # then open http://127.0.0.1:6206
```

### Pick a brain

| brain | setup | notes |
| --- | --- | --- |
| **Claude Code** (default) | install [Claude Code](https://claude.com/claude-code) and run `claude` once to log in | tamadesk runs the official `claude` CLI on your machine, as you. It never sees or stores a token. |
| **Ollama** | install [Ollama](https://ollama.com), then `ollama pull qwen3:8b` | fully offline. Choose it in Settings. |

### Start at login (Linux)

```sh
sed "s#@REPO@#$PWD#" deploy/tamadesk.service > ~/.config/systemd/user/tamadesk.service
systemctl --user enable --now tamadesk
```

## Your data

Everything lives in one folder:

- Linux: `~/.local/share/tamadesk`
- macOS: `~/Library/Application Support/tamadesk`
- Windows: `%LOCALAPPDATA%\tamadesk`

It holds `tamadesk.db` (SQLite) and `config.yaml`. Back it up, move it to a new laptop, or delete
it to start a new game. Set `TAMADESK_HOME` to put it somewhere else.

## Develop

```sh
uv run tamadesk serve --reload        # API on :6206
cd frontend && npm run dev            # UI with hot reload, proxies /api to :6206
uv run pytest && uv run ruff check .
```

See [docs/plan.md](docs/plan.md) for the roadmap, the art, motion and sound direction, and how to
add a companion.

## License

MIT. Art and sounds that ship with tamadesk are MIT too, unless a file in `frontend/src/assets`
says otherwise.
