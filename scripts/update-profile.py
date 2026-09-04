#!/usr/bin/env python3
"""
GitHub Profile README Dynamic Updater
======================================
Fetches GitHub data via REST/GraphQL API, generates futuristic SVG assets,
and regenerates dynamic sections of the profile README.md.

Zero external dependencies — uses only Python standard library.

This script is intended to live in the GitHub *profile* repository, which
GitHub requires to be named exactly after the account:

    github.com/<username>/<username>        e.g. SathyaMaragani/SathyaMaragani

REPOSITORY INCLUSION / EXCLUSION RULES
--------------------------------------
Fetched     : every public repo *owned* by the user, via `type=owner`, walking
              ALL pagination pages (per_page=100) until a short page arrives.
              The fetched count is cross-checked against `user.public_repos`
              and the run aborts if repos are missing.
Not fetched : organization repos the user only contributes to (`type=member`),
              and private repos (invisible to the public API; visible with a
              token but deliberately skipped — a profile README is public).
Statistics  : "Total Repositories" is GitHub's own `public_repos` count, so it
              includes forks and archived repos. "Total Stars"/"Total Forks"
              sum only non-fork repos, so credit is not taken for upstream work.
Featured    : forks excluded (`include_forks_in_featured`), archived excluded
              (`include_archived_in_featured`), plus anything in
              `exclude_repositories`. The profile repo (named after the user)
              is ALWAYS excluded — it is this repo, not a project.
Tech stack  : non-fork, non-excluded repos only.

FAILURE POLICY
--------------
Fetch -> validate -> generate -> validate output -> only then write.
Any failure at any stage aborts with a non-zero exit and leaves README.md and
assets/ untouched. The README is never replaced by partial or empty content.
"""

import json
import os
import sys
import re
import math
import random
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter, defaultdict

# Fix encoding for Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    try:
        if sys.stdout.encoding != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr.encoding != "utf-8":
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ============================================================
# PATHS & CONSTANTS
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
CONFIG_FILE = ROOT_DIR / "profile.config.json"
README_FILE = ROOT_DIR / "README.md"
ASSETS_DIR = ROOT_DIR / "assets"

# Repo-card text budgets, in SVG user units (px), not characters — character
# counts overflow on wide glyphs (CAPS, CJK, emoji). See fit_text().
REPO_NAME_PX = 280   # name sits left of the visibility pill
REPO_DESC_PX = 344   # 18px left margin -> 362px usable, leave a hair
TOPIC_MAX_PX = 90

# ============================================================
# COLOR PALETTE — Futuristic dark theme
# ============================================================

P = {
    "bg_darkest":     "#04060B",
    "bg_dark":        "#080B14",
    "bg":             "#0D1117",
    "bg_surface":     "#0F1419",
    "bg_card":        "#111827",
    "bg_card_alt":    "#151C28",
    "border":         "#1E293B",
    "border_glow":    "#2D1B69",
    "border_subtle":  "#1A1F2E",
    "accent_purple":  "#A855F7",
    "accent_violet":  "#8B5CF6",
    "accent_indigo":  "#6366F1",
    "accent_cyan":    "#06B6D4",
    "accent_blue":    "#3B82F6",
    "accent_pink":    "#EC4899",
    "accent_green":   "#22C55E",
    "text_bright":    "#F1F5F9",
    "text_primary":   "#E2E8F0",
    "text_secondary": "#94A3B8",
    "text_muted":     "#64748B",
    "text_dim":       "#475569",
    "contrib_0":      "#161B22",
    "contrib_1":      "#2D1B69",
    "contrib_2":      "#5B21B6",
    "contrib_3":      "#7C3AED",
    "contrib_4":      "#A855F7",
}

# Technology detection: maps language/topic names to display info
TECH_DB = {
    # Languages (from GitHub's language detection)
    "JavaScript":  {"cat": "Languages",   "color": "#F7DF1E", "icon": "JS"},
    "TypeScript":  {"cat": "Languages",   "color": "#3178C6", "icon": "TS"},
    "Python":      {"cat": "Languages",   "color": "#3776AB", "icon": "PY"},
    "HTML":        {"cat": "Languages",   "color": "#E34F26", "icon": "HT"},
    "CSS":         {"cat": "Languages",   "color": "#1572B6", "icon": "CS"},
    "Java":        {"cat": "Languages",   "color": "#ED8B00", "icon": "JV"},
    "C++":         {"cat": "Languages",   "color": "#00599C", "icon": "C+"},
    "C#":          {"cat": "Languages",   "color": "#239120", "icon": "C#"},
    "C":           {"cat": "Languages",   "color": "#A8B9CC", "icon": "C"},
    "Go":          {"cat": "Languages",   "color": "#00ADD8", "icon": "GO"},
    "Rust":        {"cat": "Languages",   "color": "#DEA584", "icon": "RS"},
    "Ruby":        {"cat": "Languages",   "color": "#CC342D", "icon": "RB"},
    "PHP":         {"cat": "Languages",   "color": "#777BB4", "icon": "PH"},
    "Swift":       {"cat": "Languages",   "color": "#FA7343", "icon": "SW"},
    "Kotlin":      {"cat": "Languages",   "color": "#7F52FF", "icon": "KT"},
    "Dart":        {"cat": "Languages",   "color": "#0175C2", "icon": "DT"},
    "Shell":       {"cat": "Languages",   "color": "#89E051", "icon": "SH"},
    "Lua":         {"cat": "Languages",   "color": "#2C2D72", "icon": "LU"},
    "Scala":       {"cat": "Languages",   "color": "#DC322F", "icon": "SC"},
    "Vue":         {"cat": "Frameworks",  "color": "#4FC08D", "icon": "VU"},
    "Svelte":      {"cat": "Frameworks",  "color": "#FF3E00", "icon": "SV"},
    "SCSS":        {"cat": "Languages",   "color": "#CF649A", "icon": "SS"},
    "Sass":        {"cat": "Languages",   "color": "#CF649A", "icon": "SA"},
    "EJS":         {"cat": "Languages",   "color": "#A91E50", "icon": "EJ"},
    "Jupyter Notebook": {"cat": "Languages", "color": "#F37626", "icon": "JN"},
    "PowerShell":  {"cat": "Languages",   "color": "#5391FE", "icon": "PS"},
    "Batchfile":   {"cat": "Languages",   "color": "#C1F12E", "icon": "BT"},
    # Frameworks/tools (from repo topics)
    "react":       {"cat": "Frameworks",  "color": "#61DAFB", "icon": "RE", "name": "React"},
    "nextjs":      {"cat": "Frameworks",  "color": "#EEEEEE", "icon": "NX", "name": "Next.js"},
    "next":        {"cat": "Frameworks",  "color": "#EEEEEE", "icon": "NX", "name": "Next.js"},
    "nodejs":      {"cat": "Frameworks",  "color": "#339933", "icon": "ND", "name": "Node.js"},
    "node":        {"cat": "Frameworks",  "color": "#339933", "icon": "ND", "name": "Node.js"},
    "express":     {"cat": "Frameworks",  "color": "#CCCCCC", "icon": "EX", "name": "Express"},
    "django":      {"cat": "Frameworks",  "color": "#092E20", "icon": "DJ", "name": "Django"},
    "flask":       {"cat": "Frameworks",  "color": "#CCCCCC", "icon": "FL", "name": "Flask"},
    "fastapi":     {"cat": "Frameworks",  "color": "#009688", "icon": "FA", "name": "FastAPI"},
    "angular":     {"cat": "Frameworks",  "color": "#DD0031", "icon": "NG", "name": "Angular"},
    "tailwindcss": {"cat": "Frameworks",  "color": "#06B6D4", "icon": "TW", "name": "Tailwind"},
    "tailwind":    {"cat": "Frameworks",  "color": "#06B6D4", "icon": "TW", "name": "Tailwind"},
    "bootstrap":   {"cat": "Frameworks",  "color": "#7952B3", "icon": "BS", "name": "Bootstrap"},
    "flutter":     {"cat": "Frameworks",  "color": "#02569B", "icon": "FL", "name": "Flutter"},
    "vite":        {"cat": "Frameworks",  "color": "#646CFF", "icon": "VI", "name": "Vite"},
    "electron":    {"cat": "Frameworks",  "color": "#47848F", "icon": "EL", "name": "Electron"},
    "three":       {"cat": "Frameworks",  "color": "#049EF4", "icon": "3D", "name": "Three.js"},
    "threejs":     {"cat": "Frameworks",  "color": "#049EF4", "icon": "3D", "name": "Three.js"},
    # Databases
    "postgresql":  {"cat": "Databases",   "color": "#4169E1", "icon": "PG", "name": "PostgreSQL"},
    "postgres":    {"cat": "Databases",   "color": "#4169E1", "icon": "PG", "name": "PostgreSQL"},
    "mongodb":     {"cat": "Databases",   "color": "#47A248", "icon": "MG", "name": "MongoDB"},
    "mysql":       {"cat": "Databases",   "color": "#4479A1", "icon": "MY", "name": "MySQL"},
    "redis":       {"cat": "Databases",   "color": "#DC382D", "icon": "RD", "name": "Redis"},
    "sqlite":      {"cat": "Databases",   "color": "#003B57", "icon": "SQ", "name": "SQLite"},
    "firebase":    {"cat": "Databases",   "color": "#FFCA28", "icon": "FB", "name": "Firebase"},
    "supabase":    {"cat": "Databases",   "color": "#3ECF8E", "icon": "SB", "name": "Supabase"},
    "prisma":      {"cat": "Databases",   "color": "#2D3748", "icon": "PR", "name": "Prisma"},
    # Tools
    "docker":      {"cat": "Tools",       "color": "#2496ED", "icon": "DK", "name": "Docker"},
    "kubernetes":  {"cat": "Tools",       "color": "#326CE5", "icon": "K8", "name": "Kubernetes"},
    "git":         {"cat": "Tools",       "color": "#F05032", "icon": "GT", "name": "Git"},
    "github-actions": {"cat": "Tools",    "color": "#2088FF", "icon": "GA", "name": "GitHub Actions"},
    "aws":         {"cat": "Tools",       "color": "#FF9900", "icon": "AW", "name": "AWS"},
    "vercel":      {"cat": "Tools",       "color": "#CCCCCC", "icon": "VC", "name": "Vercel"},
    "netlify":     {"cat": "Tools",       "color": "#00C7B7", "icon": "NT", "name": "Netlify"},
    "linux":       {"cat": "Tools",       "color": "#FCC624", "icon": "LX", "name": "Linux"},
    "automation":  {"cat": "Tools",       "color": "#9333EA", "icon": "AU", "name": "Automation"},
}

# ============================================================
# HELPERS
# ============================================================

def log(msg):
    print(f"  > {msg}")

def log_section(title):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}")

def fmt_num(n):
    """Format number: 1234 -> '1.2k', 12345 -> '12.3k'."""
    if n is None:
        return "0"
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)

def truncate(text, max_len, suffix="..."):
    """Truncate text to max_len characters, adding suffix if truncated."""
    if not text:
        return ""
    text = str(text)
    if len(text) <= max_len:
        return text
    if max_len <= len(suffix):
        return text[:max_len]
    return text[:max_len - len(suffix)] + suffix

# Per-character advance width as a fraction of font-size, for the
# system-ui / Helvetica stack used throughout. Rough but conservative.
_NARROW = set("ijltfrI.,:;'`|!()[]{}/\\ ")
_WIDE = set("mwMW@%")

def char_width(ch, bold=False):
    """Approximate advance width of one character, in em units."""
    cp = ord(ch)
    # Emoji, CJK, and other full-width glyphs occupy roughly a full em (or more).
    if cp > 0x2E80 or 0x2190 <= cp <= 0x2BFF:
        return 1.15
    if ch in _NARROW:
        w = 0.30
    elif ch in _WIDE:
        w = 0.90
    elif ch.isupper() or ch.isdigit():
        w = 0.62
    else:
        w = 0.53
    return w * (1.06 if bold else 1.0)

def text_width(text, font_size, bold=False):
    """Approximate rendered pixel width of `text` at `font_size`."""
    return sum(char_width(c, bold) for c in str(text)) * font_size

def fit_text(text, max_px, font_size, bold=False, suffix="…"):
    """
    Trim `text` so it renders within `max_px` at `font_size`, appending an
    ellipsis when trimmed. Width-based, so CAPS/CJK/emoji cannot overflow the
    card the way a fixed character count does.
    """
    if not text:
        return ""
    text = str(text)
    if text_width(text, font_size, bold) <= max_px:
        return text
    budget = max_px - text_width(suffix, font_size, bold)
    if budget <= 0:
        return ""
    out, used = [], 0.0
    for ch in text:
        w = char_width(ch, bold) * font_size
        if used + w > budget:
            break
        out.append(ch)
        used += w
    return "".join(out).rstrip() + suffix

def load_config():
    """Load profile configuration."""
    if not CONFIG_FILE.exists():
        log("Warning: No profile.config.json found, using defaults")
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def safe_text(text):
    """Escape text for SVG XML. Handles None, special chars, and emoji."""
    if text is None:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))

# ============================================================
# GITHUB API
# ============================================================

class APIError(Exception):
    """Raised when GitHub API returns an unrecoverable error."""
    pass

def _rate_limit_note(headers):
    """Human-readable rate-limit hint from response headers, or ''."""
    try:
        remaining = headers.get("X-RateLimit-Remaining")
        reset = headers.get("X-RateLimit-Reset")
        if remaining is None:
            return ""
        note = f" (rate limit remaining: {remaining}"
        if reset:
            when = datetime.fromtimestamp(int(reset), timezone.utc)
            note += f", resets {when.strftime('%H:%M:%SZ')}"
        return note + ")"
    except (ValueError, TypeError, AttributeError):
        return ""

def github_request(url, token=None, attempts=3):
    """
    Make a GitHub API request. Returns parsed JSON, or None on failure.

    Retries transient failures (network errors, 5xx, secondary rate limits)
    with backoff. Does NOT retry 404 — a deleted/renamed/private repo is a
    real answer, not a blip.
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "GitHubProfileUpdater/1.0",
    }
    if token:
        headers["Authorization"] = f"token {token}"

    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            note = _rate_limit_note(e.headers)
            if e.code == 404:
                log(f"Not found (404): {url}")
                return None
            if e.code in (401,):
                log(f"Auth rejected (401) — check the token: {url}")
                return None
            if e.code == 403 and "remaining: 0" in note:
                log(f"Rate limited{note} — cannot continue: {url}")
                return None  # waiting out a primary rate limit is not viable
            log(f"HTTP {e.code}{note} on attempt {attempt}/{attempts}: {url}")
        except json.JSONDecodeError as e:
            log(f"Malformed JSON from {url}: {e}")
            return None  # a bad body will not fix itself
        except (urllib.error.URLError, OSError) as e:
            log(f"Request failed on attempt {attempt}/{attempts}: {url} -- {e}")

        if attempt < attempts:
            time.sleep(2 ** attempt)  # 2s, 4s

    return None

def github_graphql(query, variables, token):
    """Make a GitHub GraphQL request with parameterized variables."""
    if not token:
        return None
    headers = {
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "GitHubProfileUpdater/1.0",
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    data = json.dumps(payload).encode("utf-8")
    try:
        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=data, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if "errors" in result:
                log(f"Warning: GraphQL errors: {result['errors']}")
                return None
            return result.get("data")
    except Exception as e:
        log(f"Warning: GraphQL request failed: {e}")
        return None

def fetch_user(username, token=None):
    """Fetch and validate user profile data. Returns dict or None."""
    log(f"Fetching user profile: {username}")
    data = github_request(f"https://api.github.com/users/{username}", token)
    if not isinstance(data, dict) or not data.get("login"):
        log("User response missing or malformed (no 'login' field)")
        return None
    return data

PER_PAGE = 100

def fetch_all_repos(username, token=None, max_pages=100):
    """
    Fetch ALL public repos owned by `username`, walking every pagination page.

    Returns (repos, complete). `complete` is False if ANY page failed —
    a truncated list would silently understate stars/repo counts, so the
    caller must abort rather than publish it.

    `type=owner` returns the user's own repos (forks included, which the
    ranking layer filters). Org repos the user is only a member of are
    intentionally out of scope for a personal profile.
    """
    log(f"Fetching repositories for: {username}")
    repos = []
    for page in range(1, max_pages + 1):
        url = (f"https://api.github.com/users/{username}/repos"
               f"?per_page={PER_PAGE}&page={page}&type=owner&sort=full_name")
        batch = github_request(url, token)

        if batch is None:
            log(f"Pagination failed on page {page} after retries — data is incomplete")
            return repos, False
        if not isinstance(batch, list):
            log(f"Page {page} was not a list (got {type(batch).__name__}) — malformed response")
            return repos, False

        repos.extend(r for r in batch if isinstance(r, dict) and r.get("name"))
        log(f"  Page {page}: {len(batch)} repos (running total: {len(repos)})")

        if len(batch) < PER_PAGE:
            log(f"Total repositories fetched: {len(repos)} ({page} page(s))")
            return repos, True

    log(f"Hit the {max_pages}-page safety cap — raise max_repo_pages in config")
    return repos, False

def fetch_repo_languages(repos, token):
    """
    Fetch the full language breakdown per repo (not just the primary language).

    One extra request per repo, so it only runs with a token — 60 anonymous
    requests/hour would not survive it. Returns {repo_name: {lang: bytes}}.
    Failures degrade to the primary language rather than aborting the run.
    """
    if not token:
        log("Skipping per-repo language breakdown (no token; using primary language only)")
        return {}
    out = {}
    for repo in repos:
        url = repo.get("languages_url")
        if not url:
            continue
        data = github_request(url, token, attempts=2)
        if isinstance(data, dict):
            out[repo["name"]] = data
    log(f"Language breakdown fetched for {len(out)}/{len(repos)} repos")
    return out

def fetch_contributions(username, token):
    """Fetch contribution calendar data via GraphQL.
    Requires authentication token (GITHUB_TOKEN works in Actions).
    Permission needed: default GITHUB_TOKEN scope (no extra scopes required).
    """
    if not token:
        log("Skipping contributions (no auth token)")
        return None
    log("Fetching contribution data via GraphQL")
    query = """
    query($username: String!) {
      user(login: $username) {
        contributionsCollection {
          totalCommitContributions
          totalPullRequestContributions
          totalIssueContributions
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                contributionCount
                date
                weekday
              }
            }
          }
        }
      }
    }
    """
    data = github_graphql(query, {"username": username}, token)
    if data and "user" in data and data["user"]:
        return data["user"]["contributionsCollection"]
    return None

# ============================================================
# REPOSITORY RANKING
# ============================================================

def repo_age_days(repo, now=None):
    """Days since the repo was last pushed to. Large number if unknown."""
    now = now or datetime.now(timezone.utc)
    stamp = repo.get("pushed_at") or repo.get("updated_at") or ""
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (now - dt).days)
    except (ValueError, AttributeError, TypeError):
        return 10_000  # unknown/malformed date sorts as ancient, never crashes

def excluded_repo_names(config, username):
    """Names never eligible for featuring: config list + the profile repo."""
    names = set(config.get("exclude_repositories", []) or [])
    if username:
        # GitHub requires the profile README repo to be named after the account.
        # It is this repository — never feature it as a project.
        names.add(username)
    return {n.lower() for n in names if n}

def is_featurable(repo, config, excluded):
    """Whether a repo may appear in Featured Repositories."""
    if repo.get("name", "").lower() in excluded:
        return False
    if repo.get("fork") and not config.get("include_forks_in_featured", False):
        return False
    if repo.get("archived") and not config.get("include_archived_in_featured", False):
        return False
    if repo.get("private"):
        return False  # a public profile must not advertise private work
    return True

def rank_repos(repos, config, username="", now=None):
    """
    Rank repositories by a weighted, recency-aware score.

        days      = days since last push
        freshness = 0.5 ** (days / half_life_days)    # slow decay of old credit
        activity  = max(0, 1 - days / recency_days)   # fast "worked on lately"

        score = (stars*stars + forks*forks)                  # popularity
                  * (stars_floor + (1-stars_floor)*freshness)  ... decayed
              + recency  * activity
              + size     * min(size_kb/5000, 1)
              + description * (1 if described else 0)
              + topics   * min(len(topics)/3, 1)
              + 10000 if listed in featured_repositories

    Two separate time terms on purpose. `freshness` (half-life 180d) stops a
    repo that earned stars years ago from permanently squatting on the profile
    — it keeps only `stars_floor` of that credit once ancient. `activity`
    (linear over 90d) is what actually reorders a set of repos that all have
    similar star counts, and it is weighted high enough to beat every static
    bonus combined, so pushing to a repo visibly promotes it.

    Every weight is configurable under `ranking_weights`. Set stars_floor to
    1.0 and recency to 0 for pure popularity ordering.

    Exclusions: see is_featurable() — forks, archived, private, the profile
    repo itself, and anything in `exclude_repositories`.
    """
    w = config.get("ranking_weights", {}) or {}
    w_stars = w.get("stars", 5)
    w_forks = w.get("forks", 3)
    w_recency = w.get("recency", 25)
    w_size = w.get("size", 3)
    w_desc = w.get("description", 3)
    w_topics = w.get("topics", 4)
    recency_days = max(w.get("recency_days", 90), 1)
    half_life = max(w.get("half_life_days", 180), 1)
    stars_floor = min(max(w.get("stars_floor", 0.4), 0.0), 1.0)

    featured_names = {n.lower() for n in (config.get("featured_repositories") or [])}
    excluded = excluded_repo_names(config, username)
    max_repos = max(int(config.get("max_featured_repos", 6) or 0), 0)
    now = now or datetime.now(timezone.utc)

    scored = []
    for repo in repos:
        if not is_featurable(repo, config, excluded):
            continue

        days = repo_age_days(repo, now)
        freshness = 0.5 ** (days / half_life)
        activity = max(0.0, 1 - days / recency_days)

        popularity = (repo.get("stargazers_count", 0) or 0) * w_stars \
                   + (repo.get("forks_count", 0) or 0) * w_forks

        score = (popularity * (stars_floor + (1 - stars_floor) * freshness)
                 + w_recency * activity
                 + w_size * min((repo.get("size", 0) or 0) / 5000, 1)
                 + w_desc * (1 if repo.get("description") else 0)
                 + w_topics * min(len(repo.get("topics") or []) / 3, 1))

        if repo.get("name", "").lower() in featured_names:
            score += 10000

        # Tie-break on recency then name so equal scores stay stable run to run
        scored.append((score, -days, repo.get("name", ""), repo))

    scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
    return [t[3] for t in scored[:max_repos]]

# ============================================================
# TECH STACK DETECTION
# ============================================================

def detect_tech_stack(repos, config, languages_by_repo=None):
    """
    Detect technologies from real repository data only.

    Evidence accepted, in order of strength:
      1. GitHub Linguist language breakdown (`/repos/:o/:r/languages`) — every
         language in the repo, not only the primary one. Languages under
         `language_min_share` of the repo's bytes are dropped so a stray
         config file does not become a claimed skill.
      2. The repo's primary `language` field (fallback when 1 is unavailable).
      3. Repo topics the owner set, matched against TECH_DB.
      4. `tech_stack_overrides` in profile.config.json (explicit human claim).

    Deliberately NOT inferred: frameworks guessed from a manifest's mere
    existence. "Has package.json" is not evidence of React. A framework only
    appears if the owner topic-tagged it or listed it in overrides.

    Forks are excluded — upstream code is not the owner's stack.
    """
    languages_by_repo = languages_by_repo or {}
    min_share = config.get("language_min_share", 0.05)
    tech_counts = Counter()
    counted_repos = 0

    for repo in repos:
        if repo.get("fork"):
            continue
        counted_repos += 1

        breakdown = languages_by_repo.get(repo.get("name"))
        if breakdown:
            total = sum(breakdown.values()) or 1
            for lang, byte_count in breakdown.items():
                if lang in TECH_DB and byte_count / total >= min_share:
                    tech_counts[lang] += 1
        else:
            lang = repo.get("language")
            if lang and lang in TECH_DB:
                tech_counts[lang] += 1

        for topic in (repo.get("topics") or []):
            topic_lower = str(topic).lower()
            if topic_lower in TECH_DB:
                tech_counts[topic_lower] += 1

    # Git: true by construction if the account has any repo at all.
    if counted_repos:
        tech_counts["git"] = max(tech_counts.get("git", 0), 1)

    # Manual overrides from config (explicitly claimed by the profile owner)
    for tech in (config.get("tech_stack_overrides") or []):
        if tech in TECH_DB and tech not in tech_counts:
            tech_counts[tech] = 1
        elif tech not in TECH_DB:
            log(f"Warning: tech_stack_overrides entry '{tech}' is not in TECH_DB — ignored")

    # Build categorized output, deduplicating by display name
    categories = defaultdict(list)
    seen_names = set()

    for tech_key, count in tech_counts.most_common():
        info = TECH_DB.get(tech_key, {})
        if not info:
            continue
        display_name = info.get("name", tech_key)
        if display_name in seen_names:
            continue
        seen_names.add(display_name)
        categories[info["cat"]].append({
            "name": display_name,
            "color": info["color"],
            "icon": info["icon"],
            "count": count,
        })

    return dict(categories)

# ============================================================
# SVG GENERATION — Hero Banner
# ============================================================

def _generate_stars_svg(count=60, w=840, h=200, seed=42):
    """Generate twinkling star elements with CSS animation."""
    rng = random.Random(seed)
    stars = []
    for i in range(count):
        x = rng.randint(0, w)
        y = rng.randint(5, h)
        r = rng.uniform(0.3, 1.2)
        opacity = rng.uniform(0.2, 0.8)
        delay = rng.uniform(0, 5)
        stars.append(
            f'<circle cx="{x}" cy="{y}" r="{r}" '
            f'fill="{P["text_bright"]}" opacity="{opacity:.2f}">'
            f'<animate attributeName="opacity" values="{opacity:.2f};{opacity*0.3:.2f};{opacity:.2f}" '
            f'dur="{2+delay:.1f}s" repeatCount="indefinite"/>'
            f'</circle>'
        )
    return "\n    ".join(stars)

def _generate_buildings_svg(w=840, base_y=240):
    """Generate cyberpunk city skyline buildings."""
    rng = random.Random(123)
    buildings = []

    # Building specs: (x, width, height, window_rows, window_cols)
    specs = [
        (20, 28, 70, 5, 2), (48, 18, 100, 8, 1), (62, 32, 55, 4, 2),
        (90, 22, 130, 10, 2), (108, 38, 75, 5, 3), (148, 16, 90, 7, 1),
        (162, 26, 60, 4, 2), (186, 20, 110, 8, 1), (204, 34, 85, 6, 2),
        (240, 28, 45, 3, 2), (270, 22, 95, 7, 1), (290, 30, 70, 5, 2),
        (420, 24, 80, 6, 2), (442, 18, 120, 9, 1), (458, 36, 65, 5, 3),
        (496, 20, 105, 8, 1), (514, 30, 50, 4, 2), (542, 26, 90, 7, 2),
        (570, 16, 75, 5, 1), (588, 34, 60, 4, 2),
        (640, 22, 110, 8, 1), (660, 28, 70, 5, 2), (690, 18, 95, 7, 1),
        (710, 32, 55, 4, 2), (738, 24, 85, 6, 2), (760, 20, 65, 5, 1),
        (780, 30, 100, 8, 2), (810, 22, 45, 3, 1),
    ]

    for x, bw, bh, wr, wc in specs:
        y = base_y - bh
        buildings.append(
            f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" '
            f'fill="{P["bg_dark"]}" stroke="{P["border_subtle"]}" stroke-width="0.5"/>'
        )
        win_w, win_h = 3, 3
        pad_x = (bw - wc * (win_w + 4)) / 2 + 2
        for row in range(wr):
            for col in range(wc):
                wx = x + pad_x + col * (win_w + 4)
                wy = y + 6 + row * (win_h + 5)
                lit = rng.random() > 0.35
                color = rng.choice([P["accent_purple"], P["accent_cyan"],
                                    P["accent_violet"], "#FFE4B5", P["accent_blue"]]) if lit else P["bg_darkest"]
                op = rng.uniform(0.4, 0.9) if lit else 0.15
                buildings.append(
                    f'<rect x="{wx}" y="{wy}" width="{win_w}" height="{win_h}" '
                    f'rx="0.5" fill="{color}" opacity="{op:.2f}"/>'
                )

    return "\n    ".join(buildings)

def generate_hero_svg(config):
    """Generate the hero banner SVG with cyberpunk cityscape."""
    W, H = 840, 300

    # Fit to the free area left of the vertical side-text column
    name = safe_text(fit_text(config.get("name") or "DEVELOPER", 470, 42, bold=True))
    subtitle = safe_text(fit_text(config.get("hero_subtitle", ""), 600, 14))
    side_text = config.get("side_text") or []
    interests = config.get("interests") or []

    # Interest tags — respecting width boundary
    tags_svg = ""
    tag_x = 25
    tag_y = H - 30
    for interest in interests:
        label = fit_text(interest, 130, 10)
        text_len = text_width(label, 10) + 20
        if tag_x + text_len > W - 25:
            break  # Stop if we'd overflow
        tags_svg += (
            f'<g transform="translate({tag_x},{tag_y})">'
            f'<rect width="{text_len}" height="22" rx="11" '
            f'fill="{P["bg_card"]}" stroke="{P["border_glow"]}" stroke-width="0.7"/>'
            f'<text x="{text_len/2}" y="14.5" text-anchor="middle" '
            f'font-size="10" fill="{P["text_secondary"]}" '
            f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">'
            f'{safe_text(label)}</text></g>\n    '
        )
        tag_x += text_len + 8

    # Side text
    side_svg = ""
    for i, word in enumerate(side_text[:6]):  # Cap at 6 words
        sy = 80 + i * 22
        side_svg += (
            f'<text x="{W - 30}" y="{sy}" text-anchor="end" '
            f'font-size="13" font-weight="700" letter-spacing="3" '
            f'fill="{P["text_muted"]}" opacity="0.5" '
            f'font-family="Consolas,Monaco,monospace">'
            f'{safe_text(word)}</text>\n    '
        )

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{P["bg_darkest"]}"/>
      <stop offset="60%" stop-color="{P["bg_dark"]}"/>
      <stop offset="100%" stop-color="{P["bg"]}"/>
    </linearGradient>
    <radialGradient id="cityGlow" cx="0.5" cy="0.85" r="0.5">
      <stop offset="0%" stop-color="{P["accent_purple"]}" stop-opacity="0.15"/>
      <stop offset="50%" stop-color="{P["accent_violet"]}" stop-opacity="0.06"/>
      <stop offset="100%" stop-color="transparent" stop-opacity="0"/>
    </radialGradient>
    <filter id="textGlow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <linearGradient id="groundLine" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="transparent"/>
      <stop offset="20%" stop-color="{P["accent_purple"]}" stop-opacity="0.4"/>
      <stop offset="80%" stop-color="{P["accent_violet"]}" stop-opacity="0.4"/>
      <stop offset="100%" stop-color="transparent"/>
    </linearGradient>
    <radialGradient id="textScrim" cx="0.35" cy="0.5" r="0.62">
      <stop offset="0%" stop-color="{P["bg_darkest"]}" stop-opacity="0.9"/>
      <stop offset="55%" stop-color="{P["bg_darkest"]}" stop-opacity="0.72"/>
      <stop offset="100%" stop-color="{P["bg_darkest"]}" stop-opacity="0"/>
    </radialGradient>
  </defs>

  <!-- Sky background -->
  <rect width="{W}" height="{H}" fill="url(#sky)"/>

  <!-- Stars -->
  <g>
    {_generate_stars_svg(50, W, 180)}
  </g>

  <!-- City glow -->
  <rect width="{W}" height="{H}" fill="url(#cityGlow)"/>

  <!-- Buildings -->
  <g>
    {_generate_buildings_svg(W, 245)}
  </g>

  <!-- Ground line -->
  <rect x="0" y="244" width="{W}" height="1.5" fill="url(#groundLine)"/>

  <!-- Scrim: keeps the headline legible where the skyline rises behind it.
       Soft-edged on every side so it reads as vignetting, not a panel. -->
  <ellipse cx="290" cy="135" rx="440" ry="125" fill="url(#textScrim)"/>

  <!-- Title text -->
  <text x="35" y="100" font-size="22" fill="{P["text_secondary"]}"
        font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif"
        font-weight="400">Hi there,</text>
  <text x="35" y="145" font-size="42" fill="{P["text_bright"]}" font-weight="800"
        font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif"
        filter="url(#textGlow)">I&#39;m {name}</text>
  <text x="35" y="180" font-size="14" fill="{P["text_secondary"]}"
        font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif"
        font-weight="400">{subtitle}</text>

  <!-- Side text -->
  {side_svg}

  <!-- Interest tags -->
  {tags_svg}

  <!-- Bottom border glow -->
  <rect x="0" y="{H-2}" width="{W}" height="2" fill="url(#groundLine)"/>
</svg>'''
    return svg

# ============================================================
# SVG GENERATION — About Cards
# ============================================================

def generate_about_svg(config):
    """Generate about cards SVG (Focus, Mindset, Interests, Quote)."""
    cards_cfg = config.get("cards", {})
    quote = config.get("quote", "") or ""   # escaped once, at render time
    W = 840
    card_w = 190
    card_h = 150
    gap = 13
    start_x = (W - (4 * card_w + 3 * gap)) / 2
    H = card_h + 30

    def make_card(x, title, emoji, items, idx):
        accent_colors = [P["accent_purple"], P["accent_cyan"], P["accent_violet"], P["accent_pink"]]
        accent = accent_colors[idx % len(accent_colors)]
        lines = ""
        for i, item in enumerate(items[:5]):  # Cap at 5 items
            lines += (f'<text x="{x+20}" y="{68 + i*22}" font-size="12" '
                      f'fill="{P["text_secondary"]}" '
                      f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">'
                      f'{safe_text(fit_text(item, card_w - 40, 12))}</text>\n      ')
        return f'''
      <g>
        <rect x="{x}" y="10" width="{card_w}" height="{card_h}" rx="10"
              fill="{P["bg_card"]}" stroke="{P["border"]}" stroke-width="0.7"/>
        <rect x="{x}" y="10" width="{card_w}" height="1" rx="0.5"
              fill="{accent}" opacity="0.5"/>
        <text x="{x+20}" y="40" font-size="14" font-weight="600" fill="{accent}"
              font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">
          {safe_text(emoji)}  {safe_text(title)}</text>
        {lines}
      </g>'''

    cards_svg = ""
    card_keys = [("focus", 0), ("mindset", 1), ("interests_card", 2)]
    for i, (key, idx) in enumerate(card_keys):
        card = cards_cfg.get(key, {})
        x = start_x + i * (card_w + gap)
        cards_svg += make_card(
            x, card.get("title", key.replace("_card", "").title()),
            card.get("emoji", ""),
            card.get("items", []),
            idx
        )

    # Quote card
    qx = start_x + 3 * (card_w + gap)
    quote_lines = []
    line_px = card_w - 50
    line = ""
    for word in quote.split():
        candidate = f"{line} {word}".strip()
        if line and text_width(candidate, 12) > line_px:
            quote_lines.append(line)
            # A single word wider than the card gets trimmed, not overflowed
            line = fit_text(word, line_px, 12)
        else:
            line = candidate
    if line:
        quote_lines.append(line)

    quote_text = ""
    for i, ql in enumerate(quote_lines[:5]):  # Cap lines
        quote_text += (f'<text x="{qx+25}" y="{70 + i*18}" font-size="12" '
                       f'fill="{P["text_secondary"]}" font-style="italic" '
                       f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">'
                       f'{safe_text(ql)}</text>\n      ')

    cards_svg += f'''
      <g>
        <rect x="{qx}" y="10" width="{card_w}" height="{card_h}" rx="10"
              fill="{P["bg_card"]}" stroke="{P["border"]}" stroke-width="0.7"/>
        <rect x="{qx}" y="10" width="{card_w}" height="1" rx="0.5"
              fill="{P["accent_pink"]}" opacity="0.5"/>
        <text x="{qx+18}" y="42" font-size="28" fill="{P["accent_purple"]}" opacity="0.3"
              font-family="Georgia,serif">&quot;</text>
        {quote_text}
        <text x="{qx+card_w-18}" y="{card_h-8}" text-anchor="end" font-size="28"
              fill="{P["accent_purple"]}" opacity="0.3"
              font-family="Georgia,serif">&quot;</text>
      </g>'''

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  <rect width="{W}" height="{H}" fill="transparent"/>
  {cards_svg}
</svg>'''

# ============================================================
# SVG GENERATION — Tech Stack
# ============================================================

def generate_tech_svg(tech_stack):
    """Generate tech stack SVG with categorized tech grid."""
    W = 840
    all_techs = []
    for cat in ["Languages", "Frameworks", "Databases", "Tools"]:
        items = tech_stack.get(cat, [])
        all_techs.extend(items[:12])

    if not all_techs:
        return None

    icon_w = 72
    icon_h = 70
    cols = min(len(all_techs), 10)
    rows = math.ceil(len(all_techs) / cols)
    gap_x = 8
    gap_y = 8
    grid_w = cols * (icon_w + gap_x) - gap_x
    start_x = (W - grid_w) / 2
    H = 55 + rows * (icon_h + gap_y) + 10

    icons_svg = ""
    for i, tech in enumerate(all_techs):
        row = i // cols
        col = i % cols
        x = start_x + col * (icon_w + gap_x)
        y = 50 + row * (icon_h + gap_y)
        color = tech["color"]
        # Ensure contrast on dark background
        if color.upper() in ("#FFFFFF", "#FFF", "#EEEEEE", "#CCCCCC"):
            color = "#C8C8C8"

        tech_label = safe_text(fit_text(tech["name"], icon_w - 8, 9))
        icons_svg += f'''
      <g transform="translate({x},{y})">
        <rect width="{icon_w}" height="{icon_h}" rx="10"
              fill="{P["bg_card"]}" stroke="{P["border"]}" stroke-width="0.5"/>
        <rect x="18" y="10" width="36" height="30" rx="6"
              fill="{color}" opacity="0.15"/>
        <text x="36" y="32" text-anchor="middle" font-size="14" font-weight="700"
              fill="{color}"
              font-family="Consolas,Monaco,monospace">{safe_text(tech["icon"])}</text>
        <text x="36" y="58" text-anchor="middle" font-size="9" fill="{P["text_secondary"]}"
              font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">
          {tech_label}</text>
      </g>'''

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  <rect width="{W}" height="{H}" fill="transparent"/>
  <text x="25" y="30" font-size="18" font-weight="700" fill="{P["text_bright"]}"
        font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">
    Tech Stack</text>
  <line x1="25" y1="40" x2="{W-25}" y2="40" stroke="{P["border"]}" stroke-width="0.5"/>
  {icons_svg}
</svg>'''

# ============================================================
# SVG GENERATION — Stats Card
# ============================================================

def generate_stats_svg(user_data, stats):
    """
    Generate the GitHub stats card. Every number comes from the API:
      public_repos / followers / following -> user endpoint
      stars, forks, language mix, fork & archive counts -> repo endpoint
    """
    SANS = "-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif"
    username = safe_text(fit_text(user_data.get("login", ""), 260, 14, bold=True))

    W, H = 840, 200
    L_X, L_W = 25, 300          # left panel
    R_X, R_W = 345, 470         # right panel
    C_Y, C_H = 48, 145

    rows = [
        ("Public Repositories", fmt_num(user_data.get("public_repos", 0))),
        ("Total Stars Earned",  fmt_num(stats["total_stars"])),
        ("Followers",           fmt_num(user_data.get("followers", 0))),
        ("Following",           fmt_num(user_data.get("following", 0))),
    ]
    rows_svg = ""
    for i, (label, value) in enumerate(rows):
        y = 105 + i * 22        # starts below the divider at y=88 — no overlap
        rows_svg += f'''
      <text x="{L_X + 20}" y="{y}" font-size="12.5" fill="{P["text_secondary"]}"
            font-family="{SANS}">{label}</text>
      <text x="{L_X + L_W - 20}" y="{y}" text-anchor="end" font-size="12.5"
            font-weight="600" fill="{P["text_bright"]}"
            font-family="{SANS}">{value}</text>'''

    # Language mix — share of non-fork repos whose primary language is X
    langs = stats["top_languages"][:4]
    max_count = max((c for _, c in langs), default=1) or 1
    bar_x, bar_max = R_X + 130, R_W - 130 - 70
    lang_svg = ""
    for i, (lang, count) in enumerate(langs):
        y = 104 + i * 22
        width = max(4, bar_max * count / max_count)
        color = TECH_DB.get(lang, {}).get("color", P["accent_violet"])
        lang_svg += f'''
      <text x="{R_X + 20}" y="{y}" font-size="12" fill="{P["text_secondary"]}"
            font-family="{SANS}">{safe_text(fit_text(lang, 100, 12))}</text>
      <rect x="{bar_x}" y="{y - 9}" width="{width:.1f}" height="11" rx="3"
            fill="{color}" opacity="0.75"/>
      <text x="{bar_x + width + 8:.1f}" y="{y}" font-size="11" fill="{P["text_muted"]}"
            font-family="{SANS}">{count}</text>'''

    if not langs:
        lang_svg = f'''
      <text x="{R_X + 20}" y="112" font-size="12" fill="{P["text_muted"]}"
            font-family="{SANS}">No language data available</text>'''

    def plural(n, word):
        return f"{n} {word}" if n == 1 else f"{n} {word}s"

    composition = " &#183; ".join([
        plural(stats["owned_count"], "source"),
        plural(stats["fork_count"], "fork"),
        f'{stats["archived_count"]} archived',
        f'{fmt_num(stats["total_forks"])} forks received',
    ])

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  <defs>
    <linearGradient id="statsBorder" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{P["border_glow"]}" stop-opacity="0.6"/>
      <stop offset="100%" stop-color="{P["border"]}" stop-opacity="0.3"/>
    </linearGradient>
  </defs>
  <rect width="{W}" height="{H}" fill="transparent"/>

  <text x="25" y="28" font-size="18" font-weight="700" fill="{P["text_bright"]}"
        font-family="{SANS}">GitHub Stats</text>
  <text x="{W - 25}" y="28" text-anchor="end" font-size="11" fill="{P["text_muted"]}"
        font-family="{SANS}">{composition}</text>
  <line x1="25" y1="38" x2="{W - 25}" y2="38" stroke="{P["border"]}" stroke-width="0.5"/>

  <rect x="{L_X}" y="{C_Y}" width="{L_W}" height="{C_H}" rx="10"
        fill="{P["bg_card"]}" stroke="url(#statsBorder)" stroke-width="0.7"/>
  <text x="{L_X + 20}" y="{C_Y + 26}" font-size="14" font-weight="700"
        fill="{P["text_bright"]}" font-family="{SANS}">{username}</text>
  <line x1="{L_X + 15}" y1="{C_Y + 40}" x2="{L_X + L_W - 15}" y2="{C_Y + 40}"
        stroke="{P["border"]}" stroke-width="0.5"/>
  {rows_svg}

  <rect x="{R_X}" y="{C_Y}" width="{R_W}" height="{C_H}" rx="10"
        fill="{P["bg_card"]}" stroke="url(#statsBorder)" stroke-width="0.7"/>
  <text x="{R_X + 20}" y="{C_Y + 26}" font-size="14" font-weight="700"
        fill="{P["accent_purple"]}" font-family="{SANS}">Most Used Languages</text>
  <line x1="{R_X + 15}" y1="{C_Y + 40}" x2="{R_X + R_W - 15}" y2="{C_Y + 40}"
        stroke="{P["border"]}" stroke-width="0.5"/>
  {lang_svg}
</svg>'''

# ============================================================
# SVG GENERATION — Contribution Graph
# ============================================================

def _contribution_fallback(reason):
    """
    Honest placeholder when contribution data could not be retrieved.

    Draws no cells at all — an empty grid would read as "no contributions",
    which is a different and misleading claim from "we could not fetch this".
    """
    W = 840
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} 56" width="{W}" height="56">
  <rect width="{W}" height="56" fill="transparent"/>
  <text x="{W/2}" y="26" text-anchor="middle" font-size="13" fill="{P["text_secondary"]}"
        font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">Contribution activity unavailable</text>
  <text x="{W/2}" y="44" text-anchor="middle" font-size="10" fill="{P["text_dim"]}"
        font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">{safe_text(reason)}</text>
</svg>'''

def generate_contribution_svg(contribution_data):
    """Generate contribution graph SVG. Shows an honest fallback if no data."""
    W = 840

    if not contribution_data:
        return _contribution_fallback(
            "The GraphQL contributions API needs a token; this runs automatically in GitHub Actions")

    calendar = contribution_data.get("contributionCalendar", {})
    total = calendar.get("totalContributions", 0)
    weeks = calendar.get("weeks", [])

    if not weeks:
        return _contribution_fallback("No calendar data was returned for this account")

    # Calculate quartile-based thresholds for color levels
    all_counts = []
    for week in weeks:
        for day in week.get("contributionDays", []):
            all_counts.append(day.get("contributionCount", 0))

    non_zero = sorted([c for c in all_counts if c > 0])
    if non_zero:
        q1 = non_zero[len(non_zero)//4] if len(non_zero) > 3 else 1
        q2 = non_zero[len(non_zero)//2] if len(non_zero) > 1 else 2
        q3 = non_zero[3*len(non_zero)//4] if len(non_zero) > 3 else 4
    else:
        q1, q2, q3 = 1, 2, 4

    def get_color(count):
        if count == 0: return P["contrib_0"]
        if count <= q1:  return P["contrib_1"]
        if count <= q2:  return P["contrib_2"]
        if count <= q3:  return P["contrib_3"]
        return P["contrib_4"]

    cell_size = 12
    gap = 3
    start_x = 45
    start_y = 30
    cells_svg = ""
    month_labels = {}

    for wi, week in enumerate(weeks):
        for day in week.get("contributionDays", []):
            weekday = day.get("weekday", 0)
            count = day.get("contributionCount", 0)
            date_str = day.get("date", "")
            x = start_x + wi * (cell_size + gap)
            y = start_y + weekday * (cell_size + gap)
            color = get_color(count)
            cells_svg += (
                f'<rect x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" '
                f'rx="2" fill="{color}"/>\n    '
            )
            if date_str and date_str.endswith("-01"):
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    month_labels[x] = dt.strftime("%b")
                except ValueError:
                    pass

    months_svg = ""
    for mx, label in sorted(month_labels.items()):
        months_svg += (
            f'<text x="{mx}" y="{start_y - 8}" font-size="9" '
            f'fill="{P["text_muted"]}" '
            f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">'
            f'{label}</text>\n    '
        )

    day_labels_svg = ""
    day_names = ["", "Mon", "", "Wed", "", "Fri", ""]
    for i, name in enumerate(day_names):
        if name:
            y = start_y + i * (cell_size + gap) + 10
            day_labels_svg += (
                f'<text x="{start_x - 8}" y="{y}" text-anchor="end" font-size="9" '
                f'fill="{P["text_muted"]}" '
                f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">'
                f'{name}</text>\n    '
            )

    H = start_y + 7 * (cell_size + gap) + 25

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  <rect width="{W}" height="{H}" fill="transparent"/>
  <text x="{W/2}" y="16" text-anchor="middle" font-size="11" fill="{P["text_muted"]}"
        font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">
    {total} contributions in the last year</text>
  {months_svg}
  {day_labels_svg}
  {cells_svg}
  <text x="{W - 160}" y="{H - 8}" font-size="9" fill="{P["text_muted"]}"
        font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">Less</text>
  <rect x="{W - 140}" y="{H - 17}" width="{cell_size}" height="{cell_size}" rx="2" fill="{P["contrib_0"]}"/>
  <rect x="{W - 124}" y="{H - 17}" width="{cell_size}" height="{cell_size}" rx="2" fill="{P["contrib_1"]}"/>
  <rect x="{W - 108}" y="{H - 17}" width="{cell_size}" height="{cell_size}" rx="2" fill="{P["contrib_2"]}"/>
  <rect x="{W - 92}" y="{H - 17}" width="{cell_size}" height="{cell_size}" rx="2" fill="{P["contrib_3"]}"/>
  <rect x="{W - 76}" y="{H - 17}" width="{cell_size}" height="{cell_size}" rx="2" fill="{P["contrib_4"]}"/>
  <text x="{W - 60}" y="{H - 8}" font-size="9" fill="{P["text_muted"]}"
        font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">More</text>
</svg>'''

# ============================================================
# SVG GENERATION — Repository Cards
# ============================================================

def wrap_text(text, max_px, font_size, max_lines=2, bold=False):
    """
    Greedy word wrap to a pixel budget. The final line is ellipsised if the
    text does not fit in `max_lines`, so nothing ever spills past the card.
    """
    if not text:
        return []
    words, lines, line = str(text).split(), [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if line and text_width(candidate, font_size, bold) > max_px:
            lines.append(line)
            if len(lines) == max_lines:
                break
            line = word
        else:
            line = candidate
    else:
        if line:
            lines.append(line)

    if not lines:
        return []
    # Anything left over gets folded into an ellipsis on the last line
    consumed = len(" ".join(lines).split())
    if consumed < len(words) or text_width(lines[-1], font_size, bold) > max_px:
        lines[-1] = fit_text(lines[-1] + " " + " ".join(words[consumed:]),
                             max_px, font_size, bold)
    return [l for l in lines if l]

def _star_icon(x, y, color):
    """A 5-point star drawn as a path — no emoji font dependency."""
    return (f'<path transform="translate({x},{y}) scale(0.55)" fill="{color}" '
            f'd="M10 0 L12.9 6.5 L20 7.3 L14.7 12.1 L16.2 19.2 L10 15.6 '
            f'L3.8 19.2 L5.3 12.1 L0 7.3 L7.1 6.5 Z"/>')

def _fork_icon(x, y, color):
    """GitHub-style fork glyph: two parents joining a child, drawn as shapes."""
    return (f'<g transform="translate({x},{y})" stroke="{color}" fill="{color}" '
            f'stroke-width="1.2">'
            f'<circle cx="1.5" cy="1.5" r="1.5" stroke="none"/>'
            f'<circle cx="9.5" cy="1.5" r="1.5" stroke="none"/>'
            f'<circle cx="5.5" cy="10" r="1.5" stroke="none"/>'
            f'<path d="M1.5 3 v1.5 a2 2 0 0 0 2 2 h4 a2 2 0 0 0 2 -2 V3" fill="none"/>'
            f'<path d="M5.5 6.5 v2" fill="none"/>'
            f'</g>')

def generate_repo_card_svg(repo, index=0, with_topics=True):
    """
    Generate one repository card.

    Every text run is fitted or wrapped to a pixel budget rather than a
    character count — a 200-char name, a CJK description or an emoji-heavy
    topic all stay inside the box.

    `with_topics` is decided once for the whole set so all cards tile at the
    same height; when no featured repo has topics the row is dropped entirely
    rather than leaving a band of dead space on every card.
    """
    SANS = "-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif"
    W = 380
    H = 150 if with_topics else 122
    PAD = 18

    raw_name = repo.get("name", "")
    raw_desc = repo.get("description") or "No description provided"
    lang = repo.get("language") or ""
    stars = repo.get("stargazers_count", 0) or 0
    forks = repo.get("forks_count", 0) or 0
    topics = (repo.get("topics") or [])[:3]
    badge = "Archived" if repo.get("archived") else ("Fork" if repo.get("fork") else "Public")

    accent_colors = [P["accent_purple"], P["accent_cyan"], P["accent_violet"],
                     P["accent_blue"], P["accent_pink"], P["accent_indigo"]]
    accent = accent_colors[index % len(accent_colors)]

    badge_w = max(44, text_width(badge, 9) + 18)
    name = safe_text(fit_text(raw_name, W - PAD * 2 - badge_w - 10, 15, bold=True))

    # Two description lines instead of one truncated line — GitHub blurbs are
    # usually longer than a single 380px row can hold.
    desc_lines = wrap_text(raw_desc, W - PAD * 2, 12, max_lines=2)
    desc_svg = "".join(
        f'<text x="{PAD}" y="{56 + i * 17}" font-size="12" fill="{P["text_secondary"]}" '
        f'font-family="{SANS}">{safe_text(line)}</text>'
        for i, line in enumerate(desc_lines))

    lang_color = TECH_DB.get(lang, {}).get("color", P["text_muted"])
    lang_display = safe_text(fit_text(lang, 150, 11))
    lang_svg = ""
    if lang:
        lang_svg = (
            f'<circle cx="{PAD + 5}" cy="100" r="5" fill="{lang_color}"/>'
            f'<text x="{PAD + 16}" y="104" font-size="11" fill="{P["text_secondary"]}" '
            f'font-family="{SANS}">{lang_display}</text>')

    # Stars / forks share the language row, right-aligned — no dead band when
    # a repo has no topics.
    counts_svg = (
        _star_icon(W - 108, 93, P["accent_purple"]) +
        f'<text x="{W - 94}" y="104" font-size="11" fill="{P["text_secondary"]}" '
        f'font-family="{SANS}">{stars}</text>' +
        _fork_icon(W - 60, 94, P["text_muted"]) +
        f'<text x="{W - 44}" y="104" font-size="11" fill="{P["text_secondary"]}" '
        f'font-family="{SANS}">{forks}</text>')

    topics_svg = ""
    tx = PAD
    for topic in (topics if with_topics else []):
        label = fit_text(topic, TOPIC_MAX_PX, 9)
        tw = text_width(label, 9) + 16
        if tx + tw > W - PAD:
            break
        topics_svg += (
            f'<rect x="{tx:.1f}" y="118" width="{tw:.1f}" height="19" rx="4" '
            f'fill="{P["bg_surface"]}" stroke="{P["border"]}" stroke-width="0.4"/>'
            f'<text x="{tx + tw / 2:.1f}" y="131" text-anchor="middle" font-size="9" '
            f'fill="{P["text_muted"]}" font-family="{SANS}">{safe_text(label)}</text>')
        tx += tw + 5

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  <defs>
    <linearGradient id="cardBorder{index}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{accent}" stop-opacity="0.45"/>
      <stop offset="100%" stop-color="{P["border"]}" stop-opacity="0.2"/>
    </linearGradient>
  </defs>
  <rect x="1" y="1" width="{W-2}" height="{H-2}" rx="10"
        fill="{P["bg_card"]}" stroke="url(#cardBorder{index})" stroke-width="0.8"/>
  <rect x="1" y="1" width="{W-2}" height="2" rx="1" fill="{accent}" opacity="0.55"/>

  <text x="{PAD}" y="32" font-size="15" font-weight="700" fill="{P["text_bright"]}"
        font-family="{SANS}">{name}</text>
  <rect x="{W - PAD - badge_w:.1f}" y="17" width="{badge_w:.1f}" height="19" rx="9.5"
        fill="{P["bg_surface"]}" stroke="{P["border"]}" stroke-width="0.4"/>
  <text x="{W - PAD - badge_w / 2:.1f}" y="30" text-anchor="middle" font-size="9"
        fill="{P["text_muted"]}" font-family="{SANS}">{safe_text(badge)}</text>

  {desc_svg}
  {lang_svg}
  {counts_svg}
  {topics_svg}
</svg>'''

# ============================================================
# SVG GENERATION — Footer
# ============================================================

def generate_footer_svg(config):
    """Generate footer SVG."""
    W, H = 840, 100
    motto = safe_text(fit_text(config.get("motto", ""), W - 200, 10))
    message = safe_text(fit_text(config.get("footer_message", ""), W - 160, 12))

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  <defs>
    <linearGradient id="footerLine" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="transparent"/>
      <stop offset="30%" stop-color="{P["accent_purple"]}" stop-opacity="0.3"/>
      <stop offset="70%" stop-color="{P["accent_violet"]}" stop-opacity="0.3"/>
      <stop offset="100%" stop-color="transparent"/>
    </linearGradient>
  </defs>
  <rect width="{W}" height="{H}" fill="transparent"/>
  <line x1="100" y1="15" x2="{W-100}" y2="15" stroke="url(#footerLine)" stroke-width="1"/>
  <text x="{W/2}" y="45" text-anchor="middle" font-size="15" font-weight="600"
        fill="{P["text_bright"]}"
        font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">
    Thanks for visiting</text>
  <text x="{W/2}" y="68" text-anchor="middle" font-size="12" fill="{P["text_secondary"]}"
        font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">
    {message}</text>
  <text x="{W/2}" y="90" text-anchor="middle" font-size="10" font-style="italic"
        fill="{P["text_muted"]}"
        font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif">
    &quot;{motto}&quot;</text>
</svg>'''

# ============================================================
# README GENERATION
# ============================================================

SECTION_NAMES = ["HERO", "ABOUT", "CURRENTLY", "TECHSTACK", "STATS",
                 "CONTRIBUTIONS", "REPOS", "CONNECT", "FOOTER"]

class MarkerError(Exception):
    """README markers are missing, duplicated, or unbalanced."""

def update_section(readme, section, content):
    """Replace content between PROFILE markers in the README.
    Returns (updated_readme, was_found).
    """
    start_marker = f"<!-- PROFILE:{section}:START -->"
    end_marker = f"<!-- PROFILE:{section}:END -->"
    pattern = re.compile(
        re.escape(start_marker) + r".*?" + re.escape(end_marker),
        re.DOTALL
    )
    replacement = f"{start_marker}\n{content}\n{end_marker}"
    if pattern.search(readme):
        return pattern.sub(replacement, readme), True
    else:
        return readme, False

def check_markers(readme):
    """
    Validate PROFILE marker integrity before touching a single byte.

    Raises MarkerError describing exactly what is wrong. The caller aborts on
    it — a corrupted marker must never cause the whole README (including the
    owner's hand-written content outside the markers) to be regenerated.
    """
    problems = []
    found = re.findall(r"<!--\s*PROFILE:([A-Z_]+):(START|END)\s*-->", readme)

    if not found:
        raise MarkerError(
            "README.md exists but contains no <!-- PROFILE:*:START/END --> markers.\n"
            "  Refusing to overwrite it — hand-written content would be destroyed.\n"
            "  Fix: restore the markers, or delete README.md to regenerate from scratch,\n"
            "  or re-run with --init to deliberately replace it."
        )

    seen = Counter(found)
    for section in {s for s, _ in found}:
        starts = seen[(section, "START")]
        ends = seen[(section, "END")]
        if starts != ends:
            problems.append(f"{section}: {starts} START vs {ends} END marker(s)")
        elif starts > 1:
            problems.append(f"{section}: duplicated {starts} times")
        elif starts == 1:
            si = readme.index(f"<!-- PROFILE:{section}:START -->")
            ei = readme.index(f"<!-- PROFILE:{section}:END -->")
            if ei < si:
                problems.append(f"{section}: END marker appears before START")
        if section not in SECTION_NAMES:
            problems.append(f"{section}: unknown section name")

    if problems:
        raise MarkerError(
            "README.md marker block is corrupted:\n    - "
            + "\n    - ".join(sorted(problems))
            + "\n  Refusing to write. Repair the markers and re-run."
        )

def build_readme(user_data, all_repos, ranked_repos, config, allow_init=False,
                 has_tech_svg=True):
    """
    Build the README. Only the marked sections change; everything outside the
    PROFILE markers is preserved byte for byte.

    Raises MarkerError if an existing README's markers are damaged, rather
    than regenerating over the owner's hand-written content.
    """
    username = user_data.get("login", config.get("github_username", ""))
    name = config.get("name", user_data.get("name") or username)

    tagline = config.get("tagline", "")

    # ── Section content ──
    hero = f'''<div align="center">
  <img src="assets/hero-banner.svg" alt="{safe_text(name)} - {safe_text(tagline)}" width="100%"/>
</div>'''

    about = f'''<div align="center">
  <img src="assets/about-cards.svg" alt="About {safe_text(name)}" width="100%"/>
</div>'''

    # No detectable languages/topics -> say so, rather than link a missing image
    tech = f'''<div align="center">
  <img src="assets/tech-stack.svg" alt="Tech Stack" width="100%"/>
</div>''' if has_tech_svg else '''<div align="center">

<em>No language or topic data available yet.</em>

</div>'''

    stats = f'''<div align="center">
  <img src="assets/stats-card.svg" alt="GitHub Stats" width="100%"/>
</div>'''

    contrib = f'''<div align="center">
  <img src="assets/contribution-graph.svg" alt="Contribution Graph" width="100%"/>
</div>'''

    repos_md = _build_repos_section(ranked_repos, username)
    currently_md = _build_currently_section(all_repos, config, username)
    connect_md = _build_connect_section(config)

    footer = f'''<div align="center">
  <img src="assets/footer.svg" alt="Footer" width="100%"/>
</div>'''

    sections = {
        "HERO": hero,
        "ABOUT": about,
        "CURRENTLY": currently_md,
        "TECHSTACK": tech,
        "STATS": stats,
        "CONTRIBUTIONS": contrib,
        "REPOS": repos_md,
        "CONNECT": connect_md,
        "FOOTER": footer,
    }

    # Update in place when a valid README already exists
    existing = README_FILE.read_text(encoding="utf-8") if README_FILE.exists() else ""
    if existing.strip() and not allow_init:
        check_markers(existing)          # raises MarkerError -> caller aborts
        readme = existing
        missing = []
        for section_name, content in sections.items():
            readme, found = update_section(readme, section_name, content)
            if not found:
                missing.append(section_name)
        if missing:
            # Markers validated above, so these are genuinely absent (e.g. a
            # section added by a newer version of this script). Append them.
            log(f"Appending sections not yet present in README: {missing}")
            for section_name in missing:
                readme += (f"\n\n<!-- PROFILE:{section_name}:START -->\n"
                           f"{sections[section_name]}\n"
                           f"<!-- PROFILE:{section_name}:END -->\n")
        return readme

    # Generate fresh README (file absent/empty, or --init)
    readme = f"""<!--
  =====================================================
  {name}'s GitHub Profile
  Auto-updated daily via GitHub Actions
  Content between PROFILE markers is auto-generated.
  You may freely edit content outside of markers.
  =====================================================
-->

<!-- PROFILE:HERO:START -->
{hero}
<!-- PROFILE:HERO:END -->

<!-- PROFILE:ABOUT:START -->
{about}
<!-- PROFILE:ABOUT:END -->

<!-- PROFILE:CURRENTLY:START -->
{currently_md}
<!-- PROFILE:CURRENTLY:END -->

<!-- PROFILE:TECHSTACK:START -->
{tech}
<!-- PROFILE:TECHSTACK:END -->

<!-- PROFILE:STATS:START -->
{stats}
<!-- PROFILE:STATS:END -->

<!-- PROFILE:CONTRIBUTIONS:START -->
{contrib}
<!-- PROFILE:CONTRIBUTIONS:END -->

<!-- PROFILE:REPOS:START -->
{repos_md}
<!-- PROFILE:REPOS:END -->

<!-- PROFILE:CONNECT:START -->
{connect_md}
<!-- PROFILE:CONNECT:END -->

<!-- PROFILE:FOOTER:START -->
{footer}
<!-- PROFILE:FOOTER:END -->
"""
    return readme

def _build_repos_section(repos, username):
    """
    Build the featured repositories section.

    Percentage-width images rather than a fixed 380px <table>: a table of two
    380px cells forces ~800px of horizontal scroll on a phone, while 48%-wide
    images reflow to one card per line inside GitHub's narrow mobile column.
    """
    if not repos:
        return ('<div align="center">\n\n'
                '<h3>Featured Repositories</h3>\n\n'
                '<em>No public repositories to feature yet.</em>\n\n'
                '</div>')

    lines = ['<div align="center">', '', '<h3>Featured Repositories</h3>', '']
    for idx, repo in enumerate(repos):
        repo_name = repo.get("name", "")
        repo_url = repo.get("html_url") or f"https://github.com/{username}/{repo_name}"
        alt = safe_text(repo_name)
        lines.append(
            f'<a href="{safe_text(repo_url)}">'
            f'<img src="assets/repo-card-{idx}.svg" alt="{alt}" width="48%"/></a>'
        )
    lines += ['', '</div>']
    return '\n'.join(lines)

def _build_currently_section(repos, config, username=""):
    """
    Build the 'Currently' section. `building` is auto-detected as the most
    recently *pushed* eligible repo (which is what "currently building"
    actually means), unless overridden in config.
    """
    currently = config.get("currently") or {}
    building = currently.get("building")

    if not building:
        excluded = excluded_repo_names(config, username)
        candidates = [r for r in repos
                      if is_featurable(r, config, excluded) and not r.get("archived")]
        if candidates:
            building = min(candidates, key=repo_age_days).get("name")

    if not building:
        building = "something new"

    learning = currently.get("learning") or "Always exploring new technologies"
    focus = currently.get("focus") or "Building useful tools and applications"

    lines = [
        '<div align="center">',
        '',
        '<table>',
        '<tr>',
        f'<td><strong>Currently Building</strong></td>',
        f'<td>{safe_text(building)}</td>',
        '</tr>',
        '<tr>',
        f'<td><strong>Learning</strong></td>',
        f'<td>{safe_text(learning)}</td>',
        '</tr>',
        '<tr>',
        f'<td><strong>Focus</strong></td>',
        f'<td>{safe_text(focus)}</td>',
        '</tr>',
        '</table>',
        '',
        '</div>',
    ]
    return '\n'.join(lines)

def _build_connect_section(config):
    """Build the social/connect section. Only shows links that exist."""
    socials = config.get("socials", {})
    links = []

    label_map = {
        "github":    "GitHub",
        "linkedin":  "LinkedIn",
        "x":         "X / Twitter",
        "portfolio": "Portfolio",
        "email":     "Email",
    }

    for key, label in label_map.items():
        url = (socials.get(key) or "").strip()
        if url:
            if key == "email" and not url.startswith("mailto:"):
                url = f"mailto:{url}"
            links.append(f'<a href="{safe_text(url)}"><strong>{label}</strong></a>')

    if not links:
        return ''

    separator = ' &nbsp; | &nbsp; '
    lines = [
        '<div align="center">',
        '',
        '<h3>Connect</h3>',
        '',
        f'<p>{separator.join(links)}</p>',
        '',
        '</div>',
    ]
    return '\n'.join(lines)

# ============================================================
# OUTPUT VALIDATION
# ============================================================

def validate_svg(name, content):
    """
    Validate one generated SVG before it is allowed near the assets dir.

    Checks that it is well-formed XML (so a stray '&' in a repo description
    cannot ship a broken image) and that it carries no active content. GitHub
    serves README images through camo into an <img>, where scripts never run —
    but a malformed or script-bearing SVG is a generator bug either way.
    """
    problems = []
    if not content or not content.strip():
        return [f"{name}: empty"]

    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        return [f"{name}: not well-formed XML ({e})"]

    if not root.tag.endswith("svg"):
        problems.append(f"{name}: root element is <{root.tag}>, expected <svg>")
    if root.get("viewBox") is None:
        problems.append(f"{name}: no viewBox — will not scale on mobile")

    banned = ("script", "foreignObject", "iframe", "use", "image", "a")
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in banned:
            problems.append(f"{name}: contains <{tag}>")
        for attr, value in el.attrib.items():
            attr_local = attr.rsplit("}", 1)[-1]
            if attr_local.startswith("on"):
                problems.append(f"{name}: event handler {attr_local}=")
            if attr_local in ("href", "src"):
                problems.append(f"{name}: external reference {attr_local}={value}")
            if "javascript:" in str(value).lower():
                problems.append(f"{name}: javascript: URI in {attr_local}")

    return problems

def validate_readme(readme, expected_assets):
    """Sanity-check generated README content before it replaces the real one."""
    problems = []
    if not readme or len(readme.strip()) < 200:
        problems.append(f"README is suspiciously short ({len(readme.strip())} chars)")

    for section in SECTION_NAMES:
        if readme.count(f"<!-- PROFILE:{section}:START -->") != 1:
            problems.append(f"section {section}: START marker not present exactly once")
        if readme.count(f"<!-- PROFILE:{section}:END -->") != 1:
            problems.append(f"section {section}: END marker not present exactly once")

    for ref in re.findall(r'src="(assets/[^"]+)"', readme):
        if Path(ref).name not in expected_assets:
            problems.append(f"references {ref}, which was not generated this run")

    return problems

# ============================================================
# WRITING
# ============================================================

def cleanup_stale_repo_cards(num_current):
    """Remove repo card SVGs from previous runs that are no longer needed."""
    if not ASSETS_DIR.exists():
        return
    for f in sorted(ASSETS_DIR.glob("repo-card-*.svg")):
        try:
            idx = int(f.stem.rsplit("-", 1)[-1])
        except ValueError:
            continue
        if idx >= num_current:
            f.unlink()
            log(f"Removed stale asset: {f.name}")

def write_if_changed(path, content):
    """Write only when content differs. Returns True if the file changed."""
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == content:
                return False
        except (UnicodeDecodeError, OSError):
            pass
    path.write_text(content, encoding="utf-8")
    return True

# ============================================================
# MAIN ORCHESTRATOR
# ============================================================

def collect_stats(user_data, repos):
    """Derive every displayed statistic from fetched API data. No constants."""
    sources = [r for r in repos if not r.get("fork")]
    lang_counts = Counter(r["language"] for r in sources if r.get("language"))
    return {
        "owned_count": len(sources),
        "fork_count": sum(1 for r in repos if r.get("fork")),
        "archived_count": sum(1 for r in repos if r.get("archived")),
        # Stars/forks count only the user's own work, not forked upstream repos
        "total_stars": sum(r.get("stargazers_count", 0) or 0 for r in sources),
        "total_forks": sum(r.get("forks_count", 0) or 0 for r in sources),
        "top_languages": lang_counts.most_common(),
    }

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    allow_init = "--init" in argv
    dry_run = "--dry-run" in argv

    print("\nGitHub Profile README Updater")
    print("=" * 50)

    # -- 1. Configuration --
    log_section("Loading Configuration")
    config = load_config()
    username = (os.environ.get("GITHUB_USERNAME")
                or config.get("github_username", "")).strip()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    if not username:
        print("ERROR: No GitHub username found.")
        print("Set GITHUB_USERNAME env var or github_username in profile.config.json")
        return 1

    log(f"Username: {username}")
    log(f"Profile repo must be named: {username}/{username}")
    # Never log the token itself, only whether one is present.
    log(f"Token: {'present' if token else 'absent (public data only, no contribution graph)'}")

    # -- 2. Fetch --
    log_section("Fetching GitHub Data")

    user_data = fetch_user(username, token)
    if not user_data:
        print("\nERROR: Could not fetch user data. README and assets left untouched.")
        return 1
    log(f"User: {user_data.get('name') or username} "
        f"({user_data.get('public_repos', '?')} public repos per API)")

    repos, complete = fetch_all_repos(
        username, token, max_pages=int(config.get("max_repo_pages", 100)))
    if not complete:
        print("\nERROR: Repository list is incomplete (API failure or page cap).")
        print("       Publishing partial data would understate your stats.")
        print("       README and assets left untouched.")
        return 1

    # -- 3. Validate fetched data --
    api_count = user_data.get("public_repos", 0)
    log(f"Pagination check: fetched {len(repos)}, API reports {api_count} public repos")
    if len(repos) < api_count:
        print(f"\nERROR: Fetched {len(repos)} repos but the API reports {api_count}.")
        print("       Pagination appears to have dropped repositories. Aborting.")
        return 1
    if api_count > 0 and not repos:
        print("\nERROR: API reports repositories but none were returned. Aborting.")
        return 1

    stats = collect_stats(user_data, repos)
    log(f"Sources: {stats['owned_count']}, forks: {stats['fork_count']}, "
        f"archived: {stats['archived_count']}")
    log(f"Stars earned: {stats['total_stars']}, forks of own work: {stats['total_forks']}")

    # -- 4. Rank --
    log_section("Ranking Repositories")
    excluded = excluded_repo_names(config, username)
    log(f"Never featured: {sorted(excluded)} (the profile repo is always excluded)")
    ranked = rank_repos(repos, config, username)
    for i, r in enumerate(ranked):
        log(f"  #{i+1}: {r['name']} "
            f"(stars={r.get('stargazers_count', 0)}, "
            f"forks={r.get('forks_count', 0)}, "
            f"{repo_age_days(r)}d since push)")
    if not ranked:
        log("No repositories eligible for featuring")

    # -- 5. Tech stack --
    log_section("Detecting Tech Stack")
    languages_by_repo = fetch_repo_languages(
        [r for r in repos if not r.get("fork")], token)
    tech_stack = detect_tech_stack(repos, config, languages_by_repo)
    for cat, items in tech_stack.items():
        log(f"  {cat}: {', '.join(t['name'] for t in items)}")

    # -- 6. Contributions --
    log_section("Fetching Contributions")
    contribution_data = fetch_contributions(username, token)
    if contribution_data:
        cal = contribution_data.get("contributionCalendar", {})
        log(f"Total contributions: {cal.get('totalContributions', 0)}")
    else:
        log("Unavailable - the graph will say so rather than show invented data")

    # -- 7. Generate --
    log_section("Generating Assets")
    assets = {
        "hero-banner.svg": generate_hero_svg(config),
        "about-cards.svg": generate_about_svg(config),
        "stats-card.svg": generate_stats_svg(user_data, stats),
        "contribution-graph.svg": generate_contribution_svg(contribution_data),
        "footer.svg": generate_footer_svg(config),
        "tech-stack.svg": generate_tech_svg(tech_stack),
    }
    if assets["tech-stack.svg"] is None:
        del assets["tech-stack.svg"]
        log("Warning: no tech stack data - tech-stack.svg not generated")

    # One height for the whole set, so the cards tile evenly
    with_topics = any(r.get("topics") for r in ranked)
    for i, repo in enumerate(ranked):
        assets[f"repo-card-{i}.svg"] = generate_repo_card_svg(repo, i, with_topics)

    try:
        readme_content = build_readme(user_data, repos, ranked, config, allow_init,
                                      has_tech_svg="tech-stack.svg" in assets)
    except MarkerError as e:
        print(f"\nERROR: {e}")
        return 1

    # -- 8. Validate generated output, before anything is written --
    log_section("Validating Generated Output")
    problems = []
    for filename, content in assets.items():
        problems += validate_svg(filename, content)
    problems += validate_readme(readme_content, set(assets))

    if problems:
        print("\nERROR: Generated output failed validation. Nothing was written.")
        for p in problems:
            print(f"  - {p}")
        return 1
    log(f"{len(assets)} SVGs well-formed, no active content, README markers intact")

    if dry_run:
        print("\nDry run - validation passed, nothing written.")
        return 0

    # -- 9. Write --
    log_section("Writing")
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    changed = [name for name, content in assets.items()
               if write_if_changed(ASSETS_DIR / name, content)]
    cleanup_stale_repo_cards(len(ranked))

    if write_if_changed(README_FILE, readme_content):
        changed.append("README.md")

    if not changed:
        print("\nNo changes detected. Profile is already up to date.")
        return 0

    print(f"\nProfile updated. {len(changed)} file(s) changed:")
    for name in changed:
        print(f"  - {name}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
