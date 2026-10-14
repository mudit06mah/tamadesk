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
- Add your resume and Bolt writes a one-page **profile card** from it in the background (your
  skills, projects and links, nothing invented). Every ask reads the card, and it's yours to edit.
  Things you ask Bolt to remember land in its Notes.
- Add a product brief or notes too (PDF, .md, .txt). Bolt reads them only when a task needs them,
  so they cost nothing otherwise.

**Tabs that know your next step:** each tab has one-click ✦ workflows for what you kept.
- **Papers:** "Write a blog post" or "Study notes".
- **Jobs:** "Draft applications". Leads: "Email them". Repos: "Compare them".

Bolt does the work, and longer writing lands in **Notes**, where you can read, edit, copy or
download it as markdown.

**Job hunting, straight from companies:**
- Hacker News "Who is hiring?" posts written by the companies themselves.
- Companies' own job boards (Ashby, Greenhouse, Lever).
- Web search limited to careers pages, with no LinkedIn or aggregator pages.

Every job has **apply ↗** to the company's own page and **email them**, which uses the hiring
address the company published.

**For developers:**
- A **Release radar** for many repos, or everything you've starred.
- **Issues to pick up:** good-first-issues, or triage of your own repos.
- **Show HN watching.**
- **Desktop pings** when a tab gets something new.
- Ask Bolt "is X still maintained?", "what did I ship this week?" or "which side projects did I
  abandon?".

See [docs/use-cases.md](docs/use-cases.md).

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

**From find to reply, without you stitching it together** (see [docs/journeys.md](docs/journeys.md)):
- Every job or lead has a **stage**: emailed, applied, replied, interview, closed. Sending moves
  it forward, and after **apply ↗** the card asks "did you apply?".
- **Inbox check** (IMAP, the same app password, read-only, every 10 minutes) matches replies in
  your threads, bounces, and "thanks for applying", interview and rejection mail from companies
  in your pipeline. Anything else is never stored.
- **Up next** on Today lists what's waiting on you, with one click for each: answer a reply (Bolt
  drafts it *in the same thread*), write a follow-up when 4 work days pass without an answer
  (two at most), send waiting drafts, or act on jobs you kept but never touched.

- **Quick capture**: one box for everything. These are instant and free, with no AI involved.
  - `bought groceries, finally fixed the bug #home` goes to your daily log, with a tag.
  - `todo send the invoice fri 5pm #acme` adds a todo with a deadline.
  - `todo stretch every weekday 11am` starts a habit. Each on-time finish grows its chain (×7!).
  - `remind me to call mom at 6pm`, or `… every sunday 6pm`.
  - `done invoice` ticks the todo that matches. `move invoice to monday` gives it a new deadline.
  - `waiting on specs from Riley by thu`: on Thursday it asks if you should nudge them.
  - `meeting design crit tomorrow 3pm for 45 min`: it goes on your timeline, with a ring before.
  - `focus 25 #client-a`: Bolt sits with you. A finished session pays XP, and your hours add up
    per tag.
  - `next` tells you the one thing to do now.
- **Capture from your phone:** mail yourself `td: buy stamps` (once mail is connected).
- **Todos** with XP, streaks and levels. Undoing a todo takes its XP back, so you can't farm it.
  - Beating a deadline pays a bonus.
  - Streak freezes (one per 7 days in a row) cover a missed day.
- **Learn by doing:** New Game asks three things. Afterwards, the example chips under the Ask box
  suggest shortcuts you haven't tried yet, and each one makes room for the next once you've used it.
- **Your companion** sits in a ring that fills with XP, with your streak and today's todos on it.
  Press ⇄ (or right-click) to swap between Blob, Sprout and Bolt.
- **Removing things:** `remove workout` (or × on a repeating todo, then "stop it") ends a habit for
  good, and "skip once" skips just this time. Bolt can remove todos and cancel reminders too.
- **Look back for free:**
  - `standup` gives yesterday, today and blockers, ready to paste.
  - The **week card** shows your stats and the title you earned ("Deadline Slayer").
- **Notifications with manners:**
  - Reminders, meetings and deadlines within the hour ring.
  - Everything else waits for the end of quiet hours or your focus session, then arrives as one
    summary.
- **Tabs you can finish:** each tab shows today's best 5, and old unseen items quietly expire. A
  sparkle means something new, instead of a count of everything unread.
- **Reminders** ring in the app and as a desktop notification.
- **Your voice**: tamadesk studies a few things you wrote (in Mail) plus your last 10 sent emails,
  and every draft follows your style. Fold the overview open, remove any point that isn't you,
  and add your own rules. Your rules always win.
- **Videos**: YouTube channel tabs show each video's description, and **tl;dr** reads the
  transcript (via yt-dlp, no login).
- **Tabs**: click a tab's title to rename it.
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

### Start at login (Linux, macOS, Windows)

```sh
uv run tamadesk install-service      # --dry-run shows what it writes
```

### Move to a new computer

```sh
tamadesk export                                 # one zip of your desk (secrets stay behind)
tamadesk import tamadesk-2026-10-09.zip         # on the new one
```

**Mail** works with Gmail, Fastmail, iCloud, Outlook, Yahoo, Zoho or any IMAP/SMTP server, using an
app password.

## Your data

Everything lives in one folder:

- Linux: `~/.local/share/tamadesk`
- macOS: `~/Library/Application Support/tamadesk`
- Windows: `%LOCALAPPDATA%\tamadesk`

It holds `tamadesk.db` (SQLite) and `config.yaml`. Back it up, move it to a new laptop, or delete
it to start a new game. Set `TAMADESK_HOME` to put it somewhere else.

## Develop

```sh
uv sync && (cd frontend && npm install)
uv run tamadesk serve --reload        # API on :6206 (TAMADESK_HOME=/tmp/desk for a throwaway desk)
cd frontend && npm run dev            # UI with hot reload, proxies /api to :6206
```

Before a pull request, all of these should pass:

```sh
uv run ruff check . && uv run ruff format --check . && uv run pytest
cd frontend && npx tsc -b && npx oxlint src && npm run build
```

**Where things go:**

| You want to add | Where |
| --- | --- |
| A new kind of tab | A template in `modules/templates/*.yaml`, plus (if needed) one `@source` function in `modules/sources.py`. |
| Something Bolt can do | A `@tool` in `assistant/tools.py`. Pair every create tool with a remove one. |
| A typed shortcut ("todo …", "focus 25") | `life/capture.py`, and the Ask box's `FREE` in `frontend/src/AskStore.tsx`. |
| A database column or table | Append to `MIGRATIONS` in `core/db.py`. Never edit an applied one. |
| Anything about time | `core/clock.py`. The database stores UTC; people see local time. |
| A sound or an animation | The tables in [docs/plan.md](docs/plan.md), then `fx/sound.ts` or `fx/Fx.tsx`. |
| A companion | `SPECIES` in `frontend/src/Companion.tsx` (see docs/plan.md). |

[CLAUDE.md](CLAUDE.md) lists the project's rules: no personal data in the repo, nothing sent without
a click, XP only for real progress, free and login-free sources, and the rest. They apply to people
and AI assistants alike. [docs/plan.md](docs/plan.md) has the roadmap, the art, motion and sound
direction, and what each version added.

## License

MIT. Art and sounds that ship with tamadesk are MIT too (the sounds are synthesized in code), unless
a file in `frontend/src/assets` says otherwise.
