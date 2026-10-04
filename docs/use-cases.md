# Use cases (persona study, v0.3)

Three personas each walked through their week against the code: a senior engineer, a vibecoder
and a GitHub explorer. Here is what came out of it.

## Works today
- **"What needs me on GitHub?"** shows PRs with review and CI state, assigned issues and review
  requests. Bolt answers through the `github_status` tool.
- **Followed feeds:**
  - Release notes of anything with an Atom/RSS feed.
  - PEPs and RFCs, blogs, status pages, Product Hunt.
  - YouTube channels.
- **Idea hunting:** "is anyone building X?" runs GitHub, HN and Exa search together.
- **Reading:** tl;dr of articles and papers. Critique of uploaded design docs with `read_doc`.
- **Outreach:** leads, then drafts in your voice, then redraft with feedback, then send.
- **On-call:** a reminder in 30 minutes and log lines. Memory recall answers "what did I do
  during last Tuesday's incident?".

## Added from this study
| Ask | How |
|---|---|
| "Follow releases of zed, neovim, ripgrep" / "…of everything I starred" | `releases` source (one tab for many repos, or `starred` through your gh login) and the *Release radar* template |
| "Good first issues in Rust" / "new untriaged issues on my lib" | `github_issues` source and the *Issues to pick up* template |
| "Watch Show HN for CLI tools" / "is my launch on HN yet?" | `hn` takes `tags` (`show_hn`, `ask_hn`). `min_points: 0` catches brand-new posts |
| "Ping me when the status page changes" | `notify: true` on any tab: a desktop notification when something new arrives |
| "What's on my plate?" / "done with the tokio review" | `list_todos` and `complete_todo` tools, on the same code path as the checkbox |
| "Is X still maintained? Compare X, Y, Z" | `repo_info` tool: stars, last push, issues, license, archived, latest release |
| "What did I ship this week?" / "which side projects did I abandon?" | GitHub page and tool: PRs merged in the last 7 days, and your repos by last push |

## Fixed from this study
- **`recall` and `day_notes` were never registered** as tools, so memory questions in Ask
  silently fell back to the 4-day summary. Now registered, with a test that every tool the
  prompt mentions exists.
- **Numbers in todos read as dates:** "todo review PR 4521" got a due date in the year 4521.
- **Scheduled `agent` tabs** can only search and read, never change the desk. They refresh at
  most every 6 hours.
- **The GitHub page** no longer crashes on partial GraphQL errors (SAML-protected orgs).
  GitHub search uses your `gh` login when present, so rate limits are hard to hit.
- **Tool replies** speak the user's local time, not UTC.
- **The same link** from two sources, or from Bolt plus a refresh, is one item.
- **Reminders** ring on their own thread, so slow fetches can't delay them.

## Out of scope (by design)
- **Posting, starring, merging or commenting on your behalf.** Nothing leaves without a click.
- **Reddit, X, LinkedIn,** or anything that needs a login or cookie.
- **Accounts with tokens:** Vercel, analytics, PagerDuty, Slack, calendars.
- **Bulk email blasts.** One reviewed email at a time.

## Next candidates
- A `name_check` tool: domain availability through RDAP, plus npm, PyPI and GitHub.
- An `osv` source for vulnerabilities in your dependencies.
- A `github_pr` tool to brief you on a PR before review.
- A click-only `star` action on GitHub items.
