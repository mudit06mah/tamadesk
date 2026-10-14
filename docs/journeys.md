# Journeys: how the pieces hand off to each other

Features only feel like an assistant when each one knows what comes next. This document follows
real goals end to end, names every hand-off, and says which mechanism makes it work.

## The shape every journey has

```
find  ->  keep  ->  act  ->  wait  ->  follow up / respond  ->  close  ->  remember
(tab)    (triage)  (Bolt)  (inbox)       (Up next)             (stage)    (memory)
```

| Step | What carries it |
| --- | --- |
| find | tabs: free sources, refreshed on a schedule, ranked by your taste |
| keep | the item's **stage** becomes `kept` |
| act | a workflow or item button asks Bolt. The draft or note it makes is **linked to the item** (`item_id`) |
| wait | the email's Message-ID is stored. The **inbox check** matches replies and portal emails to it |
| follow up / respond | **Up next** on Today lists what's waiting on you, each with one click |
| close | the stage ends as `replied`, `interview`, `rejected` or `done`, and the tab's progress view shows it |
| remember | every step is an event. The nightly memory digest records it, and recall finds it |

## 1. Job seeker

> "I want a remote UI/UX role at a company I'd actually like."

1. **Find:** the Job hunt tab only keeps what fits: the level you said in New Game (internship,
   junior, senior…) and your roles. A senior role never reaches an internship search. It pulls HN "Who is hiring?" posts, companies' own ATS boards, and
   careers pages from web search. Each card has **apply ↗** and the hiring email the company
   published.
2. **Keep:** ♥ the good ones. The stage becomes `kept`.
3. **Act:** two options.
   - ✦ *Draft applications* gives Bolt the kept jobs. For each one it reads the posting, reads
     your resume (`read_doc`), and writes a short, specific email into Mail, linked to the job.
   - Or **apply ↗** opens the company's portal. When you come back, the card asks "applied?",
     and one click sets the stage to `applied`.
4. **Send:** sending from Mail sets the stage to `emailed`.
5. **Wait:** the inbox check (every 10 minutes, IMAP, your Gmail) finds:
   - a reply in the thread: stage `replied`, a desktop ping, and Up next "Answer Everai".
   - "Thanks for applying" from the company or its ATS: stage `applied`, no action needed.
   - an interview invite (schedule, call, next steps): stage `interview` and Up next "Reply to
     schedule". The reply is a draft; nothing is sent automatically.
   - "Unfortunately…": stage `rejected`. Quietly closed, no ping.
6. **Follow up:** 4 business days after sending with no reply, Up next shows "Follow up with
   Everai?". One click has Bolt write a short follow-up *in the same thread* into Mail.
7. **Remember:** "which companies did I apply to in October?" works through recall over events.

## 2. Founder doing outreach

> "Find 20 small agencies that could use my product and pitch them."

The same pipeline with different sources and inputs:
- **Leads tab:** company search on Exa.
- **✦ Email them** uses the **product brief** you uploaded instead of the resume.
- **Replies** go to Up next. Bolt drafts answers using the brief and the thread.
- **Recall** answers "who showed interest last week?" by searching `replied` items and their
  messages.

## 3. Researcher who blogs

> "Stay on top of my field and write about it."

1. **Find:** the Papers tab (arXiv) and News tab (HN, RSS).
2. **Keep:** papers you'd cite.
3. **Act:** ✦ *Write a blog post* produces a Note in your voice, connecting the kept papers.
   ✦ *Study notes* produces one note per paper.
4. **Refine:** on the note page, "ask Bolt to revise" (same title, so it's a new version). Edit
   by hand. Download `.md`.
5. **Close:** used papers move to `done`, so they don't come back as suggestions.
6. **Remember:** "what was that paper about graph transformers I wrote about?" works through recall.

## 4. Developer

> "Keep my open-source work moving."

1. **GitHub page:** your PRs with review and CI state, assigned issues, review requests, what
   shipped this week, and repos gathering dust.
2. **Ask** "which stuck PR first?". Bolt reads the PR status and makes a todo with the link and a
   reminder.
3. **Release radar and Issues tabs:** ✦ *Pick one for me* creates a todo for a good first issue.
4. **Recap:** in the evening it mentions what got merged, through `github_status` with shipped PRs.

## 5. Learning from video

> "Follow a few channels without the algorithm."

1. **Videos tab:** YouTube channel RSS, with each video's description on the card.
2. **tl;dr** reads the **transcript** (through yt-dlp, which agent-reach installs) and summarizes
   what the video actually says.
3. ✦ *Watch list* creates todos for the videos worth watching, shortest first.

## 6. The daily rhythm

- **Morning, on Today:** one list, in this order (`life/today.py`, and Bolt's `my_day` tool).
  - **Needs you:** replies to answer, follow-ups due, each draft waiting, interviews to schedule,
    jobs kept but not acted on, overdue todos. Each carries its **only you** lines: the
    things only you can do well ("reply today, they asked a question", "check this guessed
    address", "say why this company").
  - **The timeline:** meetings (with a join link and a ring before each), reminders and todos due,
    with a "now" line. What you already did folds away under "earlier", including ticked
    suggestions.
  - **Anytime:** undated todos and ones due later. A deadline shows as a countdown that heats up
    as it gets close, and the companion gets louder in your chosen nudge style.
  - **Bolt's line:** a short line pointing at the single most important item (the next meeting
    if it's within the hour).
  - Every row links to its draft (`#mail/d12`), its item (`#m:jobs/i4`) or its tab, and drafts
    and meeting items open in place with the same cards the pages use.
- **During the day:**
  - The Ask box handles anything ad hoc.
  - The free shortcuts (`todo … every weekday`, `done`, `move`, `waiting on`, `meeting`,
    `focus`, `next`, `remove`) cost nothing, and work from your phone by mailing yourself
    `td: …`.
  - A focus session holds every non-urgent ping until it ends.
  - When a meeting ends, Today asks what you promised.
- **Evening, at the recap hour:**
  - The recap is the day's last row: written for you, or now if you ask.
  - The recap summarizes the day, including pipeline changes: 2 sent, 1 reply, 1 interview.
- **Night:** the memory digest writes the day to `memory/YYYY-MM-DD.md`.

## Rules these journeys rely on

- **Nothing leaves without a click.** Bolt drafts, and you send.
- **Inbox reading is narrow.** tamadesk only stores mail that belongs to something you started:
  a reply in one of your threads, or a message from a company in your pipeline. Everything else is
  ignored and never stored.
  - The one exception is a **calendar invite** addressed to you (you're an attendee or the
    organizer). Only the event is kept: title, times, recurrence, meeting link and organizer. The
    mail body, description and other attendees are never stored. It can be switched off in Settings.
  - An invite from a company in your pipeline moves that item to `interview`.
- **Your calendar feed is a secret.** The private iCal address lives in `secrets.json`, never in
  the API, logs or error messages. Feed and mail copies of an event merge on its iCal UID.
- **Suggestions are rules first.** Only-you lines come from plain regex rules. Claude is asked
  only when you press "anything else?" on a draft. A dismissed suggestion never comes back. XP comes
  only when the data shows it happened (a reply was sent, the placeholder is gone), and undo
  takes it back.
- **Stages are earned, not guessed.**
  - Moving forward (`emailed`, `replied`) comes from real events.
  - Classification from keywords (`applied`, `interview`, `rejected`) is shown with the message
    that caused it, so you can see why.
  - You can always move an item back.
- **Every hand-off is visible:**
  - a draft says which item it's for
  - an item shows its draft or thread
  - Up next says why something is there
