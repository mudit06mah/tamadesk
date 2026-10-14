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

## What's in v0.1

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

## The assistant (v0.3): ask first, manual second

The top of the desk is one box: **ask Bolt to do it**. Each ask runs the user's own `claude -p`:
- `--mcp-config` plugs in tamadesk's MCP server (`assistant/mcp.py`, a small stdio JSON-RPC loop
  with no SDK) and agent-reach's login-free servers from `~/.mcporter/mcporter.json` (Exa).
- `--tools WebFetch` is the only built-in tool, so there's no shell and no file edits.
- `--max-budget-usd` caps each ask. `--resume` continues the conversation.
- `stream-json` with partial messages turns into NDJSON events the UI animates: the companion's
  bubble shows the current step, and step chips stack up in the reply.

**Tools** (`assistant/tools.py`) reuse the same code as the buttons:
- `search` (any free source)
- `read_page`
- `list_tabs`, `create_tab`, `delete_tab`, `add_to_tab`, `tab_items`
- `add_todo`, `set_reminder`, `log`
- `draft_email`

**Budget:**
- Per-ask and daily caps in Settings. Every Claude call lands in `usage` (ask, agent_tab, summary,
  recap, voice).
- The Ask box shows today's spend, and each reply shows its own cost in API-equivalent dollars.
- Shortcuts (`todo`, `remind me`, `log`) never reach Claude.

**Mail** replaces Write:
- Drafts come from Bolt (`draft_email`), from a lead's ✉ button, or from you.
- Sending goes through Gmail SMTP with an app password in `<home>/secrets.json` (0600).
- Dry run by default, with a daily cap and an opt-out line on outreach.
- Guessed addresses need an explicit "I checked this".

### v0.3.1: layout, GitHub, documents, themes
- **Sidebar:**
  - Today, Mail, Notes, GitHub and Memory stay pinned (Memory later replaced the Journal).
  - The user's tabs live in a scrolling list.
  - Theme, sound and settings are pinned at the bottom.
- **GitHub** (`life/github.py`): one `gh api graphql` query for open PRs (review decision, CI rollup),
  assigned issues and review requests, cached 5 minutes. Also a `github_status` tool.
- **Documents** (`life/docs.py`): PDF/md/txt stored as text. The system prompt lists them, and
  `read_doc` fetches one only when needed.
- **Themes** (`frontend/src/themes.ts`): each palette is a set of CSS variables. `crt` adds
  scanlines and `dark` flips color-scheme. Adding one takes a single line.
- The swipe deck was removed: every tab is the same ranked list.

### v0.4.2: a desk that knows you, and leaner calls
- **Profile card** (`life/profile.py`): adding a resume writes a one-page card in the background
  (one light call through the user's brain). It lives in `memory/profile.md`, is editable in
  Settings, and every ask reads it, so Bolt rarely needs the full resume.
  - Links come from the resume by regex.
  - A line with a number the resume doesn't have is cut back or dropped (a test run turned
    "20 readers" into "20+ users").
  - Empty about answers (level, roles, location) are filled from it. The user's own words, including
    "looking for", always win.
  - Bolt's `remember` with `note` adds to the card's Notes, which survive a rebuild.
- **Lean Claude calls:** every `claude -p` runs with tamadesk's own system prompt
  (`--system-prompt`, not the coding-agent one). None of the user's own setup is loaded: no
  claude.ai connectors such as Gmail or Drive, no skills, no hooks (`--strict-mcp-config`,
  `--disable-slash-commands`, `--setting-sources ""`). It only affects the processes tamadesk
  starts. Measured with the same tasks and models:

  | call | before | after |
  | --- | --- | --- |
  | a light JSON call (company screen, haiku) | 17,000 tokens, $0.036 | 1,600 tokens, $0.003 |
  | a Bolt ask (add a todo, sonnet) | 35,800 tokens, $0.080 | 18,000 tokens, $0.039 |

  Bolt kept its tool use and its persona rules (a jailbreak attempt got "nice try ^_^").
- **Deadlines:** set or move one by winding a clock (one turn is 12 hours, and winding past
  midnight moves to the next day), tap a day, or type words. "No deadline" clears it.
- **Tooltips:** every `title` shows as a small ink card (`Tips.tsx`) instead of the browser's black
  box.
- **Learning roadmaps** (`layout: steps`, the `roadmap` source, `modules/youtube.py`): "videos to
  understand neural networks", or a pasted syllabus, becomes a tab of topics in order. Each topic
  gets the few best videos, chosen with no tokens: an on-topic title, explainer length (no Shorts),
  and well watched. Watched videos stay ticked in place, and a progress bar counts steps. A finished
  step bursts, and a finished path gets a banner.
- **Videos you can judge at a glance:** thumbnail, length, views, and a description with the
  channel's promo removed (links, sponsors, "help fund", shop lines). Videos Bolt adds by hand get
  their details from yt-dlp once.
- **Bookmark / not for me** replace keep / skip. Both teach the tab's ranking. The tab now says what
  it learned ("more 'rust', less 'crypto'"), and every card shows when it was published.
- **Tossing is a toss:** a dropped todo, a passed item or a tossed draft crumples into a paper ball
  and lands in a pixel bin.
- **Your day, wake to bed:** New Game (and Settings) asks when you usually wake and go to bed.
  The recap is written at bedtime (1 AM for a night owl), quiet hours default to the night, and the
  day turns over halfway through the night (`core/clock.py`). So 12:30 AM still counts as today, and
  an earlier-than-usual morning already counts as the new one.
- **A better synth:** the `cozy` palette (now the default) is small instruments built in WebAudio:
  a wooden marimba, FM glass bells, soft thumps and filtered air, through a room reverb and a gentle
  compressor. The first palette stays as `classic` (pick one in Settings). A recorded sample pack
  was tried and dropped: it sounded dated next to the synth.
- **Undo everywhere:** after anything a misclick could do (tick, remove, toss a draft, pass or
  bookmark, dismiss a tip, move or clear a deadline), a bar offers Undo for 7 seconds, and Ctrl/⌘+Z
  works too (`fx.offerUndo`). Pages reload through `tamadesk:refresh`.
- **Recap picks are your todos:** "for tomorrow" points at open todos by id. A reworded copy of one
  ("Knock out Tiktok setup") maps back to it, so "+ todo" never duplicates; it shows "on your list",
  or ✓ once done. A recap written before 20:00 is "so far": nothing still due today counts as missed.
- **Focus from a todo:** a todo due within 3 hours shows "▶ focus till then", which ends at the
  deadline. Any other todo offers "▶ 25m" on hover.
- **News that stays on topic:**
  - The `news` source reads Bing News' public RSS and links to the publisher's own page.
  - Hacker News topic searches need every word, in the title or text, with no typo matches. "Starlink
    India" had been pulling in any story that said "India": 50 off-topic items in one tab.
  - A tab's `match` words drop anything that mentions none of them.
  - A new tab is checked for relevance, not just for returning results. Bolt then looks at what it
    found before it replies.
  - The "Follow a story" template sets all of this up.
- **Small fixes:** code in answers and notes is a real code block with a copy button. `t` (like `/`)
  jumps to the Ask box. The deadline clock opens on today.
- **Fixed:** Bolt's day brief now gives full dates for anything not today. "Fri 17:00" next week was
  being read as last Friday.

### v0.4.1: job search that finds real, open postings
Measured on a real internship search: the old single combined query found 0 good postings.
- **Several narrow, posting-shaped queries** (two phrasings per role), with retries when Exa
  answers empty (it sometimes does).
- **Originals only:** company job systems (Greenhouse, Lever, Ashby, Workable, SmartRecruiters,
  Recruitee) or the company's careers pages. Boards, aggregators, school career centres and
  portfolio boards are dropped.
- **Learn the boards:** a result on a company's job system (or a careers page powered by
  Greenhouse) adds that company's whole board to the tab, read directly from then on.
- **Verify:** postings found by search are opened and dropped if closed (at most 25 per refresh).
  Postings over 60 days old are dropped. Kept postings are re-checked daily, and closed ones say
  so and leave Up next.
- **Screen:** companies are checked against what the user said to avoid or wants (Settings, or
  Bolt's `remember`). Free word rules come first, then one light batched call per new company
  through the user's own brain, with the verdict cached.
- **Result:** 0 → 9 good postings (7 confirmed open) on the same search, plus 2 company boards
  watched.
- **Next:** ranking by your skills (from the profile card), posting details pulled out for
  drafting, voice from real examples and learning from edits.

### v0.4: play every day (persona study, docs/use-cases.md)
- **Free shortcuts for everything daily** (`life/capture.py`):
  - repeating todos and reminders ("every weekday 10am")
  - `done X`, `move X to fri`
  - `waiting on X from Y by thu`
  - `meeting X at 3pm for 45 min`
  - `focus 25 #tag`
  - `next`
  - #tags on anything
- **Capture from your phone:** mail yourself `td: …`. (Later: phone notifications, e.g. ntfy or
  Telegram, as an opt-in, since that sends data to a third party.)
- **Removing:** `remove X` / `cancel the X reminder` (free). × on a repeating todo asks "skip once"
  or "stop it". A series never has two open copies, and Bolt has `drop_todo` and `cancel_reminder`.
- **Habit chains:** each on-time finish of a repeating todo grows its chain, with a banner at 3, 7,
  14, 30, 50 and 100.
- **Streak freezes:** one per 7 days in a row (hold 2), spent automatically on a missed day.
- **Focus sessions** (`life/focus.py`):
  - The companion sits with you.
  - A finished session is +2 XP per 5 minutes; stopping early earns nothing.
  - Minutes add up per #tag, so freelancers get hours per client.
- **After a meeting:** "anything you promised?" turns each line into a linked todo.
- **Looking back** (`life/review.py`, free):
  - a standup note
  - the week card, with the title you earned
  - a brag doc
- **Learning by doing** (`life/tips.py`): New Game asks 3 questions. The Ask box's example chips
  then suggest the shortcuts you haven't tried yet, one or two at a time.
- **The companion ring:** the XP bar is a ring around the companion, with the streak, today's todos
  and freezes on it. ⇄ (or a right-click) opens a wheel to switch companions. A happy companion
  bobs gently every few seconds instead of hopping all the time.
- **Keyboard:** Escape leaves a text box, so `/` and 1–9 work again.
- **Calm, not quiet** (`life/notify.py`):
  - quiet hours and focus hold non-urgent pings, which are then summarised once
  - tab pings are batched
  - tabs show a sparkle instead of a count, and their best 5 first; unseen items expire
    (`expire_days`)
  - Windows gets toast notifications
- **Reach:**
  - GitHub notifications (review requested, mentions, CI) as "needs you" rows
  - deadline calendars (Canvas, Moodle…) become todos
  - a CFPs tab from the public conference-data repo
  - any mail provider
  - `export`/`import`, and `install-service` for all three systems
  - the UI is built into the wheel

### v0.3.3: Today, calendar, only-you
- **Today is the spine** (`life/today.py`): what needs you, then the day's timeline (meetings,
  reminders, todos due, what you did), then undated todos. Every row links to its draft, item or
  tab (`#mail/d12`, `#m:jobs/i4`). Bolt reads the same thing with `my_day`.
  - Merged: up_next, todos, alarms, today's log and the recap window.
  - Hidden behind a click: the voice panel in Mail, and what you already did today ("earlier").
- **Calendar** (`life/calendar.py`, zero tokens):
  - Sources: invites in the mail tamadesk already reads, plus an optional private iCal address,
    read every 15 minutes.
  - Events merge on UID; the higher SEQUENCE wins, and the feed wins ties.
  - Recurrence and timezones come from `recurring-ical-events`.
  - A ring comes before each meeting (0 XP: the calendar talking isn't progress).
  - Later: "Add to calendar" as a downloadable .ics.
- **Fit** (`modules/fit.py`, zero tokens): a tab or a search can declare
  `fit: {level, roles, avoid, min}`.
  - The level comes from the title (intern, junior, mid, senior); the role from title words.
  - Items below `min` (default 0.6) are dropped and never fetched again. A wrong level, like a
    senior role for an internship search, scores 0.
  - New Game asks "Looking for work right now?" with one-tap answers. Bolt asks one short question
    when the level or role is unclear, then remembers it.
- **Deadlines that build pressure** (`life/pressure.py`):
  - A todo's deadline is set in plain words ("fri 5pm").
  - A countdown chip heats up at a day, 3 hours and an hour, and when the todo is late.
  - The companion's line and one desktop ping per step use the user's own nudge style (gentle,
    hype, strict, deadpan).
  - Beating the deadline is +5 XP, and undo takes all of it back.
- **Only you** (`life/suggest.py`): regex rules on mail and drafts.
  - The rules: a direct question, a deadline (with "remind me"), a guessed address (it gates
    Send), the company never named, a placeholder or stock opener, a meeting with them soon.
  - Claude is asked only on a click, and then only light and capped.
  - Done, dismissed or undone; XP only when the data proves it.

### v0.3.2: memory
- **Conversation state** lives in `AskStore` above the pages. Streams survive navigation, and the
  last chat is restored from localStorage.
- **Raw layer:** SQLite FTS5 `recall` (porter stemming), filled by triggers on messages, log,
  todos, drafts and kept items.
- **Daily digests:** a light-model job at 03:30 (and 2 minutes after startup) turns each finished
  day into `<home>/memory/YYYY-MM-DD.md`. Each file is a summary plus facts whose `#tags` are broader
  words, so semantic recall works with plain full-text search.
  - **The files are the source of truth.** `sync_files` re-indexes edited files, and a deleted
    file means that day is forgotten for good.
- **Tools:** `recall` (Bolt expands the query with synonyms and categories) and `day_notes`.
  The last 4 days' summaries ride along in the prompt.
- **Later:** weekly/monthly roll-up files for "what did I do in September", and optional local
  embeddings if FTS + tags ever falls short.

## Modules: tabs that adapt to the user (v0.2)

The UI is not generated. A **module** is a YAML file in `<home>/modules/`. It names its sources,
schedule, view and actions, and the frontend draws it with one of a few hand-polished views.

The beauty lives in those views, which are designed once. The YAML only combines them.

```yaml
name: Papers
icon: book            # book | news | code | target | eye | play | pen | star
view: feed            # feed (ranked list) | deck (swipe one at a time)
every: daily 08:00    # 30m | 6h | 7d | daily HH:MM
sources:
  - {type: arxiv, query: "graph neural networks, protein folding"}
interests: [gpu]      # boosts items from day one
actions: [save, skip, summarize, todo, open]
reasons: []           # deck only: quick skip reasons
```

- **Sources** (`modules/sources.py`): one function each, registered with `@source("name")`.
  - `rss`, `arxiv`, `hn`, `github`: free official APIs.
  - `exa`: agent-reach's login-free web search via mcporter.
  - Jina Reader reads pages, for summaries.
  - Never any login, cookie or scraping-hostile channel (LinkedIn, X, Reddit and so on).
- **Ranking** (`modules/rank.py`): word log-odds learned from save/skip, plus the module's
  declared interests. It's pure Python with no model to load, and it explains itself.
- **Templates** (`modules/templates/*.yaml`): the gallery. `${param}` fields become the form in
  the "new tab" dialog and in New Game.
- **"Describe it"** goes to the assistant, which designs the tab with `create_tab`. The spec is
  validated in code, so a bad answer can't break the app.
- **`agent` source:** for fuzzy needs no query can express, a capped Claude run curates items on
  each refresh. It costs tokens, so Bolt is told to prefer real sources.
- **Token policy:** fetching, ranking and rendering cost zero tokens. Reasoning happens when the
  user asks for it, within their caps.
- **Compute policy:**
  - At most 2 scheduler threads.
  - Each module keeps its best `keep` unseen items. Pruned and old skipped items become tiny
    "gone" rows, so they aren't fetched again, and are deleted after 90 days.

Next views: `queue` (approve or redraft outgoing things), `board` (status columns), `stats`.
Next sources: YouTube search via agent-reach's yt-dlp, Semantic Scholar, Product Hunt RSS, GitHub
trending.

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
  only for ambient loops, and for whole-content swaps: moving to another day on Today is one short
  ease-in-out slide of the whole day (the old one leaves before the new one arrives), never
  row-by-row.
- **Squash and stretch, anchored at the feet:** companions breathe (scaleY 0.96) and land with a
  squash. Never scale from the center.
- **Things go somewhere:** a captured note flies into the window it belongs to, and that window
  bumps. Nothing just appears.
- **Celebrate in proportion:**
  - A todo gets a checkbox burst and a +XP float.
  - Reaching the daily goal gets a banner.
  - A level up gets a banner plus confetti.
- **Throwing away goes somewhere:** a tossed card scrunches into a ball, arcs up and drops into a
  bin that pops up in the corner. The bin's lid opens, then it wobbles shut. With reduced motion,
  the card just goes.
- **Small things spring too:** a tooltip pops from its tail after a short hover, with no sound. The
  deadline clock springs open from its chip. Its hand follows the pointer directly while dragged
  and settles with a slight overshoot after a key press. Its face tints lavender from 18:00 to 06:00.
- **Cheap by construction** (measured with a 4x CPU slowdown):
  - Endless loops (the companion breathing and hopping, zzz) are CSS animations on `transform`, so
    the GPU runs them and an idle desk does no work per frame. They used to be JS loops, about 90
    page updates every 1.5 seconds.
  - Switching lists or days moves one GPU layer (`will-change`), never every card. Pills slide with
    a CSS transition (`SegTabs`), not a layout animation.
  - Today keeps the days around the one you're on, so moving a day doesn't wait on the server.
- **Respect `prefers-reduced-motion`:** everything degrades to fades.

## Sound design

All sounds are synthesized live (WebAudio, `fx/sound.ts`), so they are tiny and need no licensing.
The `cozy` palette (the default) is a few small instruments, each meaning one kind of thing:
- **Marimba** (wood: a sine bar plus its 4x partial and a mallet tick) for everyday actions.
- **Bells** (FM: bright at the strike, a clean tone after) for rewards and arrivals.
- **Thumps** (a falling low sine) give a landing its weight.
- **Noise** (filtered) for clicks, paper, the wind-up key's ratchet and lids.
- Everything goes through a small room reverb and a gentle compressor, so stacked layers stay level.

Rules:
- Soft attacks so nothing clicks. Notes come from C major pentatonic, so overlapping cues still sound
  good together.
- Good things rise in pitch and removals fall.
- Loud for the big moments (a todo done, a level, a reminder), near-silent for the constant ones
  (typing, dial ticks, page switches).
- Nothing plays on hover, and every sound respects the mute toggle.
- The `classic` palette (plain sine/triangle blips) stays one switch away in Settings.

| cue | when | cozy |
| --- | --- | --- |
| tap | navigation | one short wooden note |
| capture | quick capture landed | two wooden notes, up |
| check | todo done | a soft landing, three wooden notes up, a bell to finish |
| undo / drop | undo, or something removed | wooden notes falling (drop adds a breath of air) |
| stamp | something saved | a rubber stamp: a short slap over a low thump |
| send | mail sent | air rushing up, a quick wooden run, a bell as it leaves |
| ring | a reminder fires | a music-box phrase on glass bells, twice |
| poke | click the companion | a springy boing |
| hatch | pick a companion (New Game or the wheel) | a 5-note wooden arpeggio and a bell |
| start | GAME START / a focus session begins | a short chiptune fanfare, then a bell |
| levelup | level up / goal / focus done / week card | a wooden run up and a bright bell chord ringing out |
| click | switching pages | a small tactile click: a crisp tick with a little body under it |
| keep / skip | bookmark / not for me | wood and a little glass, up / a soft swipe down |
| step | each step Bolt takes while working | the scale, climbing one note per step |
| arrive | Bolt's answer arrives | a warm rolled bell chord over a low wooden note |
| sparkle | a new theme | high bells, glittering |
| open / close | a dialog | a rounded pop up / down, with a little air |
| type / key | New Game typewriter / typing in the Ask box | tiny key clicks |
| tick | winding the deadline clock, one per 15-minute notch | a wind-up key, soft and modern: two clean little clicks with a faint metallic glint, lifting slightly as you keep winding |
| lock | a deadline is set | the key's last notches, a latch thunk, a small two-note bell |
| crumple | tossing something away | paper crackles |
| bin | the toss lands | a thump, a tin can, the lid |

Reused cues: a ticked suggestion plays `check` if it earned XP, `stamp` if not, and dismissing one
plays `drop`. Clearing a deadline plays `drop`. A toss plays `crumple`, then
`bin`. Finishing a roadmap step plays `levelup`. A finished profile
card plays `arrive`. A meeting alert is a reminder, so it plays `ring`. Moving between days on Today plays
`tap`, and expanding a row plays `open`/`close`.

## Data model

SQLite, migrations in `core/db.py` (append-only). Tables:
- `profile`: key/value JSON (about, companion, voice, onboarded).
- `samples`
- `log_entries`
- `todos`
- `reminders`
- `drafts`
- `events`: every XP-bearing action, which is the source of truth for XP, levels and streaks.
