# tamadesk plan

The source of truth for scope, direction and phase order.

## The idea

A desk companion that makes getting through the day feel like a small adventure. You talk to it
in one box, and it keeps your log, todos and reminders, writes in your voice, and recaps your day.
Everything you finish feeds a creature that lives on your screen.

Principles:

1. **Local first.** One data folder, one SQLite file. No account, no server, no telemetry.
2. **Bring your own brain.** The user's own Claude Code login (default) or a local Ollama model.
   tamadesk never holds an API key or a token.
3. **Feels like a game, works like a tool.** Motion and sound reward real progress, never busywork.
   XP comes only from finishing things, and undo takes it back.
4. **Sounds like you.** Drafts come from a voice profile built from your own writing, plus a
   deterministic anti-slop pass.
5. **Small and hackable.** It's plain FastAPI + React. A companion is a text drawing, and a
   sound is a few lines of WebAudio.

## The brain, and the terms

- `claude_code` runs the official `claude` binary as a subprocess, under the user's own
  subscription login, on the user's own machine. This is the same as the user running
  `claude -p` themselves.
  - tamadesk never proxies or shares anyone's subscription.
  - It never passes `--bare` or an API key, and it strips `ANTHROPIC_API_KEY` from the child environment.
  - It runs with `--tools ""`, so the brain can only return text. It can't touch files or the
    shell, even if a log entry contains something prompt-like.
- `ollama` uses the local HTTP API with JSON-schema structured output, fully offline.
- **Later:** an `anthropic_api` brain for people who prefer their own API key. It would be opt-in
  and stored in the OS keychain, never in config.yaml.

Every brain call is `ask(prompt, schema) -> dict`. Adding a brain means one file in `brain/`.

## What's in v0.1 (this commit)

- **New Game** onboarding:
  - A title screen.
  - Seven typed-out questions; answers go to profile `about`.
  - Choose and name a companion.
  - Paste writing samples.
  - A brain check.
  - It can be replayed from Settings.
- **Quick capture** (`life/capture.py`), with a live preview chip of what Enter will do:
  - `todo …` adds a todo.
  - `remind me … at 6pm / in 20 min / tomorrow 9am` sets a reminder.
  - Anything else goes to the log.
- **Today:**
  - The companion, with moods and a speech line.
  - Level/XP, done-today/goal, streak.
  - Todos, alarms, today's log, and the evening recap.
- **Reminders:** a scheduler rings them every 20s. You get a desktop notification, an in-app alarm
  dialog and a music-box sound, plus +3 XP when you dismiss one.
- **Evening recap:** runs at `recap_hour` (local time), or on demand. Its "for tomorrow" items
  can become todos with one click.
- **Write:** add samples and "study my voice" (the profile is built once), then draft emails from a
  one-line ask, with Copy, Redo and Toss.
- **Journal:** every log line, grouped by day.
- **Settings:** brain kind and model, recap hour, daily goal.

## Roadmap

### v0.2: make it feel alive
- [ ] **Companion growth:** stages (egg, baby, teen, adult) unlocked by level. Sprout grows a
      leaf per streak week. Accessories as level rewards.
- [ ] **Companion needs (gentle):** it gets sleepy if you don't log for a day, and cheers up on
      the first capture. There is never guilt, death or punishment.
- [ ] **Motion pass:** hatch animation in New Game; level-up evolution; todo checkbox "stamp";
      items physically sliding between windows; idle micro-animations (looking around,
      stretching).
- [ ] **Sound pass:** a sound-design table (below) with a volume slider, a "cozy"/"chiptune"
      sound pack switch, and optional lo-fi ambient loops while a focus timer runs.
- [ ] **Focus timer** (pomodoro) that the companion "sits with", giving XP per completed block.

### v0.3: daily rhythm
- [ ] Morning brief: today's todos and reminders, plus what you said you'd do yesterday.
- [ ] Weekly review: a recap of the week and streak chart, written by the brain.
- [ ] Recurring todos and reminders ("every weekday 9am").
- [ ] Natural-language edits ("move invoice to friday").

### v0.4: mail
- [ ] Gmail send with an app password in the OS keychain, dry-run by default, nothing sent
      without an explicit click.
- [ ] Follow-up reminders on sent mail; IMAP reply detection that plays a celebration.
- [ ] A deterministic "voice lint" (banned phrases, dashes, unsourced numbers) on every draft.

### Packs (optional, later)
Packs are self-contained feature sets someone can turn on. The first one is **Job Hunt**, ported
from an earlier job-outreach prototype: scouting companies, reviewing drafts, an outbox and try-it quests. Packs add dock tiles, XP rules and
scheduler jobs through one small registration function.

### Distribution
- [ ] `uvx tamadesk` / `pipx install tamadesk` with the UI pre-built into the wheel.
- [ ] macOS launch agent + Windows startup shortcut, alongside the systemd unit.
- [ ] A tiny native window (pywebview or Tauri) so it's a desk app, not a browser tab.

## Art direction

- **Look:** a playful retro desktop. Cream windows with chunky ink outlines and hard drop shadows
  on a dotted lavender desk ("paper"), or a green CRT with scanlines ("phosphor").
- **Fonts:** DotGothic16 for the interface, VT323 for things you read or type, DSEG7 for numbers.
- **Companions:** 14px-wide pixel sprites with a fixed palette (the same colours in every theme):
  - ink `#2c2934`, lavender `#a48ed9`, sage `#8dbd98`/`#cfe2d1`, butter `#f1d27e`,
    coral `#e98c7b`, blush `#f3a9ba`, paper `#fffaf0`.
- **Wanted from contributors:**
  - Companion sheets (idle, blink, happy, sleepy, plus growth stages).
  - A title-screen illustration.
  - Window icons.
  - A desk background scene with a day/night cycle.

### Add a companion

In `frontend/src/Companion.tsx`, add an entry to `SPECIES`:
- `top`, `eyes` and `bottom` are rows of single characters, all exactly 14 wide.
- `eyes` needs 2-row variants for idle, happy, sleepy and blink.
- `fill` maps characters to colours, and `.` is transparent.

Then add a `{species, label, blurb}` entry to `COMPANIONS` in `life/onboarding.py`.

## Motion design

- **Springs over easings** for anything the user caused (dialogs, cards, banners). Use easings
  only for ambient loops.
- **Squash and stretch, anchored at the feet:** companions breathe (scaleY 0.96) and land with a
  squash. Never scale from the center.
- **Things go somewhere:** a captured note flies into the window it belongs to, and that window
  bumps. Nothing just appears.
- **Celebrate in proportion:**
  - A todo gets a checkbox burst and a +XP float.
  - Reaching the daily goal gets a banner.
  - A level up gets a banner plus confetti.
- **Respect `prefers-reduced-motion`:** everything degrades to fades.

## Sound design

All sounds are synthesized live (WebAudio, `fx/sound.ts`), so they are tiny and need no
licensing. Rules:
- Use sine and triangle waves, with soft attacks so nothing clicks.
- Good things rise in pitch and removals fall.
- Nothing plays on hover, and every sound respects the mute toggle.

| cue | when | shape |
| --- | --- | --- |
| tap | navigation | sine bubble gliding up |
| capture | quick capture landed | two quick rising bubbles |
| check | todo done | soft thud + two bright triangle notes |
| undo | undo or drop | the same two notes, falling |
| ring | reminder fires | 4-note music-box phrase, twice |
| poke | click the companion | random-pitch bubble |
| hatch | pick a companion | 5-note rising arpeggio |
| type | New Game typewriter | very quiet high tick |
| start | GAME START | short square-wave fanfare |
| levelup | level up / goal | 4-note triangle arpeggio |

## Data model

SQLite, migrations in `core/db.py` (append-only). Tables:
- `profile`: key/value JSON (about, companion, voice, onboarded).
- `samples`
- `log_entries`
- `todos`
- `reminders`
- `drafts`
- `events`: every XP-bearing action, which is the source of truth for XP, levels and streaks.
