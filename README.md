# tamadesk

A tiny pixel companion that lives on your desk and turns your day into an adventure.

Tell it what you did, what you need to do, and when to poke you. It keeps a daily log, tracks
your todos, rings your reminders, writes emails that actually sound like you, and recaps your day
every evening. Every finished thing earns XP. Your companion levels up with you.

tamadesk runs entirely on your own machine. There's no account, no server and no telemetry.
The writing is done by **your own** Claude Code (or a local model via Ollama).

> Status: early, playable alpha. Expect sharp edges and new companions.

## What it does

**Ask your companion to do things, and it does them.** One box at the top of your desk:

- *"Keep an eye on new GitHub repos about agent tools that cut token usage, and pixel-art tools"*:
  Bolt designs precise searches, makes a tab that refreshes every morning, fills it, and shows
  you the best few right away.
- *"Find 15 small e-commerce brands in Europe that might need my design studio, with a contact"*:
  a lead deck you swipe through. Press ✉ on a lead and Bolt researches it and drafts an email in
  your voice into **Mail**.
- *"Every morning, the best new papers on climate modelling"*, *"remind me to call mom at 6"*,
  *"what changed in the latest Python release?"*: the same box.

You watch every step as it happens: "searching GitHub…", "hatching a tab…", "drafting…".

**Under the hood:**
- Bolt runs on **your own Claude Code**, plugged into tamadesk's tools over MCP and into
  agent-reach's login-free web search. It can't use a shell or edit files.
- **You set the budget:** a cap per ask and a daily cap. Every answer shows roughly what it used.
- `todo …`, `remind me …` and `log …` are handled instantly on the desk and cost nothing.

**Memory:**
- Every conversation is saved and survives tab switches and reloads.
- Every chat, log line, todo and email is searchable instantly, for free.
- Each night your companion writes the day down as a short markdown file:
  `memory/2026-10-03.md`, holding a summary plus standalone facts tagged with broader words.
  "Wants to try the omakase place" is tagged `#japanese #food #dish`, so *"what was that japanese
  dish I wanted to try?"* finds it a month later.
- The files are yours: read them, fix a fact, or delete a day to make it forget.

**GitHub:** your open PRs with review decision and CI state, issues assigned to you, and PRs
waiting for your review, all through your own `gh` login. Ask Bolt "which stuck PR should I fix
first?".

**You:**
- Settings → You holds everything your companion knows about you (interests, stack, what you
  offer), editable anytime.
- Add your resume or a product brief (PDF, .md, .txt). Bolt reads them only when a task needs
  them, so they cost nothing otherwise.

**Themes:** twelve palettes, from lavender paper and sakura to Game Boy, amber CRT and midnight
neon.

**Tabs** are what Bolt (or you, from the gallery) builds for recurring needs:
- They're small YAML files with free sources: arXiv, Hacker News, GitHub, RSS, and Exa web search.
- A tiny local ranker learns your taste from what you keep and skip.
- Refreshing a tab costs no tokens, unless it uses an `agent` source for needs that no search can
  express.

**Mail:**
- Bolt's drafts wait for you there. You edit them and send through your Gmail with an app
  password.
- It starts in dry run, with a daily cap.
- Outreach emails get an opt-out line.
- Guessed addresses are flagged UNSURE until you check them.

- **Quick capture**: one box for everything.
  - `bought groceries, finally fixed the bug` goes to your daily log.
  - `todo send the invoice` adds a todo.
  - `remind me to stretch in 20 min` or `remind me to call mom at 6pm` sets a reminder.
- **Todos** with XP, streaks and levels. Undoing a todo takes its XP back, so you can't farm it.
- **Reminders** ring in the app and as a desktop notification.
- **Your voice**: paste a few emails or essays you wrote (in Mail). tamadesk studies them once,
  and every draft follows your style.
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

### Free data sources

Every tab pulls from free, login-free sources:

- **arXiv**, **Hacker News** (Algolia) and **GitHub search**, through their public APIs.
- **Any RSS/Atom feed**: blogs, news sites, YouTube channels.
- **Web search**, through [agent-reach](https://github.com/Panniantong/agent-reach)'s login-free
  channels: Exa search via `mcporter`, and Jina Reader to read pages for summaries. Install it with
  `pipx install agent-reach && agent-reach install`. Only the Leads and Web watch tabs need it.

Fetching, ranking and storage all run on your machine. The fetch jobs use at most two threads,
and old items are pruned, so tamadesk stays small.

- Asks run on the model and effort you choose (Settings → assistant), within your caps.
- Small background jobs (tl;dr summaries, the recap, studying your voice) use the cheapest model.

### Pick a brain

| brain | setup | notes |
| --- | --- | --- |
| **Claude Code** (default) | install [Claude Code](https://claude.com/claude-code) and run `claude` once to log in | tamadesk runs the official `claude` CLI on your machine, as you. It never sees or stores a token. |
| **Ollama** | install [Ollama](https://ollama.com), then `ollama pull qwen3:8b` | fully offline. Choose it in Settings. |

### Start at login (Linux)

```sh
sed -e "s#@REPO@#$PWD#" -e "s#@PATH@#$PATH#" deploy/tamadesk.service > ~/.config/systemd/user/tamadesk.service
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
