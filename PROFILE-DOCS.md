# Dynamic GitHub Profile README — Documentation

A GitHub profile README whose statistics, featured projects, tech stack and
contribution graph are regenerated from the GitHub API every day. Nothing is
hardcoded, and nothing is invented: if a number cannot be fetched, the run
aborts rather than publishing a guess.

---

## 1. Deployment — the profile repository

GitHub only renders a profile README from a repository **named exactly after
the account**. For the account `SathyaMaragani` that is:

```
github.com/SathyaMaragani/SathyaMaragani
```

Any other name is an ordinary repository and will not appear on the profile.

**Bootstrap:**

1. Create a new **public** repository named exactly your username.
   GitHub shows a "you found a secret!" banner when the name matches.
2. Push the contents of this project to it (`README.md`, `profile.config.json`,
   `PROFILE-DOCS.md`, `scripts/`, `assets/`, `.github/`).
3. Edit `github_username` in `profile.config.json` if it does not already
   match the account.
4. **Actions → Update Profile README → Run workflow** to verify it end to end.

The profile repository is **never featured as a project** — the generator
excludes any repository whose name matches the account name, with or without
a config entry.

---

## 2. File structure

```
SathyaMaragani/
├── README.md                       # the profile (generated between markers)
├── profile.config.json             # the ONLY manually edited data file
├── PROFILE-DOCS.md                 # this file
├── scripts/
│   ├── update-profile.py           # fetch → validate → generate → validate → write
│   └── test_update_profile.py      # self-check, no network, no framework
├── assets/                         # generated; do not edit by hand
│   ├── hero-banner.svg
│   ├── about-cards.svg
│   ├── tech-stack.svg
│   ├── stats-card.svg
│   ├── contribution-graph.svg
│   ├── repo-card-0.svg … repo-card-5.svg
│   └── footer.svg
└── .github/workflows/update-profile.yml
```

---

## 3. Which repositories are included

| | Fetched | Counted in stats | Eligible to be featured | Counted in tech stack |
|---|---|---|---|---|
| Public source repos | yes | yes | yes | yes |
| Forks | yes | in `public_repos` and the fork count only | no *(configurable)* | **no** |
| Archived repos | yes | yes | no *(configurable)* | yes |
| The profile repo (`user/user`) | yes | yes | **never** | yes |
| `exclude_repositories` entries | yes | yes | no | yes |
| Private repos | no | no | never | no |
| Org repos the user only contributes to | no | no | no | no |

Notes on the deliberate choices:

- **Pagination is exhaustive.** `?per_page=100` is walked page by page until a
  short page arrives — 2 repos fetch 2, 150 repos fetch all 150. The only cap
  is `max_repo_pages` (default 100 pages ≈ 10,000 repos), and hitting it is
  treated as a failure, not a silent truncation.
- **The fetched count is cross-checked** against `user.public_repos`. If
  fewer repos come back than GitHub says exist, the run aborts instead of
  publishing understated numbers.
- **"Total Stars Earned" excludes forks** — a fork inherits the upstream
  project's star count, and claiming those would be dishonest. Forks still
  appear in "Public Repositories", because that is GitHub's own count.
- **Org repositories are out of scope.** `type=owner` is used deliberately;
  a personal profile featuring an organisation's repositories would be
  misleading about ownership. Add them to `featured_repositories` by name
  only if you own them.

---

## 4. `profile.config.json` — the single source of manual data

This file holds **only** what the API cannot know. No GitHub statistic is
duplicated here; the self-check asserts that.

| Field | Purpose |
|---|---|
| `github_username` | Account to fetch. Overridden by `GITHUB_USERNAME`. |
| `name`, `tagline`, `bio`, `hero_subtitle` | Hero banner copy |
| `interests`, `side_text` | Hero tags and the vertical side text |
| `cards` | Focus / Mindset / Interests card contents |
| `quote`, `motto`, `footer_message` | About-card quote and footer copy |
| `currently` | `building` / `learning` / `focus`. `null` → auto-detected |
| `socials` | Links. Empty strings are omitted from the README entirely |
| `featured_repositories` | Names to force to the top |
| `exclude_repositories` | Names to hide (the profile repo is automatic) |
| `include_forks_in_featured` | Default `false` |
| `include_archived_in_featured` | Default `false` |
| `max_featured_repos` | Default `6` |
| `max_repo_pages` | Pagination safety cap, default `100` pages |
| `tech_stack_overrides` | Extra technologies to claim explicitly |
| `language_min_share` | Ignore languages below this share of a repo's bytes |
| `ranking_weights` | See below |

`currently.building` set to `null` auto-detects the most recently **pushed**
eligible repository, which is what "currently building" actually means.

---

## 5. Ranking algorithm

```
days      = days since the repo was last pushed to
freshness = 0.5 ** (days / half_life_days)     slow decay of old credit
activity  = max(0, 1 - days / recency_days)    fast "worked on lately"

score = (stars×stars + forks×forks)                     popularity
          × (stars_floor + (1 − stars_floor) × freshness)  … decayed
      + recency     × activity
      + size        × min(size_kb / 5000, 1)
      + description × (1 if the repo has a description)
      + topics      × min(len(topics) / 3, 1)
      + 10000       if listed in featured_repositories
```

Two time terms, on purpose:

- `freshness` (half-life 180 days) stops a repo that earned stars years ago
  from permanently squatting on the profile — once ancient it keeps only
  `stars_floor` (40%) of that credit.
- `activity` (linear over 90 days) is what reorders repos with similar star
  counts, and is weighted high enough (25) to outrank every static bonus
  combined. Pushing to a repository visibly promotes it.

Defaults, all overridable in `ranking_weights`:

```json
{
  "stars": 5, "forks": 3, "recency": 25,
  "size": 3, "description": 3, "topics": 4,
  "recency_days": 90, "half_life_days": 180, "stars_floor": 0.4
}
```

Set `"stars_floor": 1.0, "recency": 0` for pure popularity ordering.

---

## 6. Tech stack detection

Technologies are only claimed when repository data supports them:

1. **Linguist language breakdown** (`/repos/:owner/:repo/languages`) — every
   language in the repo, not just the primary one. Requires a token; without
   one the primary `language` field is used instead. Languages below
   `language_min_share` (5%) of a repo's bytes are dropped, so one stray
   config file does not become a claimed skill.
2. **Repository topics** you set yourself, matched against the built-in
   technology table.
3. **`tech_stack_overrides`** — an explicit human claim. Unknown entries are
   ignored with a warning rather than rendered blank.

Explicitly **not** done: inferring frameworks from the mere existence of a
manifest. A `package.json` is not evidence of React. Frameworks appear only
if you topic-tag the repository or list them in the overrides.

Forks contribute nothing — upstream code is not your stack.

---

## 7. Authentication

| | Token | What works |
|---|---|---|
| GitHub Actions | built-in `GITHUB_TOKEN`, injected automatically | everything |
| Local, no token | none | profile, repos, stats, ranking, tech stack (primary language only). Contribution graph shows its honest fallback. |
| Local, with token | `GITHUB_TOKEN=…` env var | everything |

No credential is ever hardcoded, and the script logs only whether a token is
*present* — never its value.

```bash
python scripts/update-profile.py                      # anonymous, 60 req/hr
GITHUB_TOKEN=ghp_xxx python scripts/update-profile.py  # 5,000 req/hr
```

```powershell
$env:GITHUB_TOKEN = "ghp_xxx"; python scripts/update-profile.py
```

**Minimum permission for the contribution graph:** a classic PAT with the
single scope `read:user`. Nothing broader — never `repo`. In Actions the
built-in `GITHUB_TOKEN` normally suffices; if the GraphQL contributions query
is rejected for it, add a `read:user` PAT as a repository secret named
`PROFILE_TOKEN` and the workflow prefers it automatically.

### CLI flags

| Flag | Effect |
|---|---|
| *(none)* | Normal run |
| `--dry-run` | Fetch, generate and validate; write nothing |
| `--init` | Deliberately regenerate a README that has no markers (destructive) |

---

## 8. Failure policy

```
fetch → validate fetched data → generate → validate generated output → write
```

Nothing is written until every stage passes. The README is never replaced by
partial, empty or malformed content.

| Scenario | Behaviour |
|---|---|
| API unreachable / 5xx | 3 retries with backoff, then exit 1, files untouched |
| Rate limited (403, remaining 0) | Logged with the reset time, exit 1, files untouched |
| Failure part-way through pagination | Exit 1 — partial repo lists are never published |
| Fetched count < `public_repos` | Exit 1 — treated as dropped repositories |
| Malformed JSON / wrong shape | Rejected as malformed, exit 1 |
| Repo deleted, renamed or made private | Simply absent from the next run's data |
| Missing description / language / topics / avatar | Rendered with a neutral placeholder |
| No social links configured | The Connect section is omitted entirely |
| Contribution data unavailable | "Contribution activity unavailable" — no fake grid |
| No language or topic data at all | Honest text instead of a broken image link |
| Generated SVG malformed or script-bearing | Exit 1 before anything is written |
| README markers missing or corrupted | Exit 1 with the exact problem named |
| Nothing changed | Files left byte-identical; the workflow makes no commit |

---

## 9. README marker integrity

Generated content lives strictly between:

```html
<!-- PROFILE:SECTION:START -->
<!-- PROFILE:SECTION:END -->
```

Sections: `HERO`, `ABOUT`, `CURRENTLY`, `TECHSTACK`, `STATS`,
`CONTRIBUTIONS`, `REPOS`, `CONNECT`, `FOOTER`.

Everything outside the markers is preserved byte for byte — add your own
sections freely.

Before writing, the markers are checked for: unbalanced START/END pairs,
duplicates, an END before its START, and unknown section names. Any problem
**aborts the run with a message naming the section**, because the alternative
— regenerating the file — would destroy hand-written content. A README with
no markers at all is likewise refused; pass `--init` if you genuinely want it
replaced.

---

## 10. Idempotency

Running the generator repeatedly produces byte-identical output:

```
python scripts/update-profile.py     # updates
python scripts/update-profile.py     # "No changes detected."
python scripts/update-profile.py     # "No changes detected."
```

No timestamp, date or "last updated" string is written into the README or the
assets — a timestamp would force a commit every single day even when nothing
about the profile actually changed. The decorative starfield and skyline use
fixed random seeds for the same reason. Files are only written when their
content differs, so an unchanged asset does not even get its mtime touched.

The only things that legitimately change day to day are real data: the
contribution graph, repository ranking as activity shifts, and the counts.

---

## 11. GitHub Actions workflow

```yaml
permissions:
  contents: write     # required: the job pushes the regenerated files back
```

- **Daily** at 00:00 UTC, plus **manual** `workflow_dispatch`.
- `concurrency: update-profile` — a scheduled and a manual run cannot push
  simultaneously.
- `timeout-minutes: 10` so a hung request cannot burn Actions minutes.
- The self-check (`test_update_profile.py`) runs **before** the generator; a
  broken generator fails the job instead of writing bad output.
- Secrets are passed as environment variables and never echoed. The script
  logs only `Token: present`.
- `git add README.md assets` — scoped, so no stray file is ever swept into a
  commit. Commits only happen when `git diff --cached` is non-empty.
- **No infinite loop:** the workflow has no `push` trigger, and pushes made
  with `GITHUB_TOKEN` do not trigger workflow runs by design.
- If the script exits non-zero the job fails before the commit step, leaving
  the repository exactly as it was.

---

## 12. SVG safety and rendering

Generated SVGs contain **no** `<script>`, `<foreignObject>`, `<use>`,
`<image>`, `<a>`, event-handler attributes, external stylesheets, web fonts,
or any external reference. Every asset is self-contained. This is enforced,
not assumed: `validate_svg()` parses each file and fails the run on any
violation, and the self-check verifies the validator itself catches script
tags, `foreignObject`, `onclick`, malformed XML and a missing `viewBox`.

The only dynamic element is declarative SMIL `<animate>` on the hero's stars,
which renders inside an `<img>` without scripting.

All text is XML-escaped through `safe_text()`. A repository described as
`A <B> & C project` renders literally and cannot break the document —
verified by the self-check.

Fonts are system stacks (`-apple-system, Segoe UI, Helvetica, Arial`) with
`Consolas, Monaco, monospace` for code-ish labels, so nothing is fetched at
render time.

---

## 13. Text overflow

Truncation is **width-based, not character-based**. A 28-character limit
overflows the moment a name is uppercase, Japanese, or full of emoji, because
those glyphs are far wider than lowercase Latin. `fit_text()` measures an
approximate advance width per character (narrow / normal / wide / full-width
and emoji at ~1.15em) and trims to a pixel budget, appending `…`.

Applied to repository names, descriptions, topic pills, language labels,
technology labels, the hero name and subtitle, interest tags, about-card
items, the quote (wrapped by width, with over-long single words trimmed
rather than allowed to overflow), and the footer copy.

Topic pills and interest tags additionally stop early rather than run past
the edge of their container. The self-check asserts that no text element in a
repository card extends past the 380px card boundary, across 200-character
names, 500-character descriptions, CJK, emoji and empty strings.

---

## 14. Mobile rendering

Measured in headless Chrome: `document.scrollWidth == clientWidth` and
`horizontalScroll = false`. The page does not require horizontal scrolling.

- Every SVG carries a `viewBox` and is embedded at `width="100%"`, so it
  scales to GitHub's column width instead of overflowing it.
- Featured repository cards are `width="48%"` images rather than a
  fixed-width `<table>`. Two 380px table cells force roughly 800px of
  horizontal scroll on a phone; percentage widths cannot overflow their
  container at any viewport size.
- Repository cards are 380×150, or 380×122 when no featured repo has topics —
  the topics row is dropped for the whole set rather than leaving a band of
  dead space on every card. All cards in a set share one height so they tile
  evenly.
- The only remaining table is the "Currently" block. GitHub gives README
  tables `display: block; overflow: auto`, so a long value scrolls inside the
  table rather than widening the page.

Known limitation: markdown cannot carry media queries, so the two-column card
grid stays two-up on a phone (~170px per card) rather than stacking. Set
`max_featured_repos` lower, or accept slightly small cards on narrow screens.

---

## 15. Running the self-check

```bash
python scripts/test_update_profile.py
```

No network, no framework, no writes outside a temp directory. It covers:
XML escaping of `& < > " '`; 200-character, CJK and emoji names; missing
descriptions and languages; 0 / 1 / 2 / 10 / 100 / 150 repositories;
pagination across three pages; mid-pagination failure; malformed responses;
fork / archived / private / profile-repo exclusion; recency actually
outranking stale stars; unknown config overrides; contribution fallback
honesty; SVG safety; marker corruption in four shapes; and a full end-to-end
`main()` run over 157 hostile repositories, including a second run that must
change nothing on disk.

---

## 16. Troubleshooting

**"Fetched N repos but the API reports M"** — pagination lost repositories,
almost always rate limiting. Set `GITHUB_TOKEN` and re-run.

**"README.md marker block is corrupted"** — the message names the section and
the problem. Restore the marker pair, or delete `README.md` and re-run to
regenerate from scratch.

**"Contribution activity unavailable"** — expected without a token locally.
In Actions, add a `read:user` PAT as the `PROFILE_TOKEN` secret if the
built-in token is rejected.

**SVGs look stale on github.com** — GitHub's image proxy caches aggressively.
Wait a few minutes, or hard-refresh.

**Workflow never runs** — scheduled workflows are disabled on repositories
with no activity for 60 days; check the Actions tab and re-enable. Confirm
the repository name matches the username exactly.

---

## 17. Design system

| Token | Colour | Usage |
|---|---|---|
| Background | `#04060B` → `#0D1117` | Sky gradient, page ground |
| Card surface | `#111827` | Card fills |
| Border | `#1E293B` | Card outlines |
| Accent purple | `#A855F7` | Primary accent |
| Accent violet | `#8B5CF6` | Secondary accent |
| Accent cyan | `#06B6D4` | Tertiary accent |
| Text bright | `#F1F5F9` | Headings and values |
| Text secondary | `#94A3B8` | Labels |
| Text muted | `#64748B` | Captions |

The palette is deliberately dark-only. GitHub renders README images
identically in both themes, and a light-theme variant would double every
asset for no gain.
