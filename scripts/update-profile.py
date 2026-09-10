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
    # Ground — a deep forest-night green rather than GitHub's neutral slate
    "bg_darkest":     "#050D0A",
    "bg_card":        "#0D211A",
    "pill":           "#102A21",
    "track":          "#12291F",
    "border":         "#1E4034",
    "border_glow":    "#2F6B52",
    "band":           "#07130E",
    "pill_hero":      "#0C2019",
    "pill_edge":      "#4E8E72",
    # Dusk valley, sky top to ground
    "sky_top":        "#245562",
    "sky_mid":        "#3E7F7C",
    "sky_haze":       "#86B49C",
    "sky_horizon":    "#D7C795",
    "sky_ground":     "#16342B",
    "cloud_lit":      "#FBEFCB",
    "cloud_lit2":     "#E4D0A2",
    "cloud_shade":    "#9DB6A8",
    "cloud_shade2":   "#6E948F",
    "mountain":       "#2A5257",
    "mountain_near":  "#1D3F41",
    "town":           "#132E2B",
    "tree_mid":       "#123024",
    "tree_dark":      "#0A1D16",
    "leaf_dark":      "#0C2418",
    "leaf_mid":       "#153A24",
    "leaf_deep":      "#061710",
    "leaf_hi":        "#4A6B2E",
    # Accents
    "emerald":        "#34D399",
    "teal":           "#2DD4BF",
    "lime":           "#86EFAC",
    "sky":            "#38BDF8",
    "gold":           "#E9C97E",
    "gold_bright":    "#FBEFC8",
    "amber":          "#D9A441",
    # Type
    "headline_mint":  "#DCF2E4",
    "text_bright":    "#EAF7F0",
    "text_primary":   "#CFE6DA",
    "text_secondary": "#93B3A6",
    "text_muted":     "#6C8C7E",
    "text_dim":       "#4E6E60",
    # Contribution heat — greens climbing to a harvest gold at the top level
    "contrib_0":      "#102A20",
    "contrib_1":      "#14532D",
    "contrib_2":      "#15803D",
    "contrib_3":      "#22C55E",
    "contrib_4":      "#FDE68A",
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
# SHARED SVG PIECES
# ============================================================

SANS = "-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Consolas,Monaco,monospace"
HAND = "Segoe Script,Bradley Hand,Brush Script MT,Snell Roundhand,cursive"

# One stylesheet, inlined into every asset. Animations are CSS rather than
# SMIL for two reasons: staggering 400 contribution cells costs one inline
# `animation-delay` instead of 400 <animate> elements, and CSS is the only
# form `prefers-reduced-motion` can switch off. Every animated element is
# authored so its *static* state is the finished state — if animation never
# runs (reduced motion, an old renderer, a feed reader), the image still
# reads correctly.
ANIM_CSS = """<style>
    .fade{animation:fade .9s ease-out both}
    .rise{animation:rise .8s cubic-bezier(.2,.75,.3,1) both}
    .grow{animation:grow 1.3s cubic-bezier(.2,.8,.3,1) both;transform-box:fill-box;transform-origin:left center}
    .pop{animation:pop .7s cubic-bezier(.2,1.5,.5,1) both;transform-box:fill-box;transform-origin:center}
    .glow{animation:glow 4.5s ease-in-out infinite}
    .spin{animation:spin 11s linear infinite;transform-box:fill-box;transform-origin:center}
    .sway{animation:sway 9s ease-in-out infinite;transform-box:view-box}
    .float{animation:float 44s ease-in-out infinite}
    .twinkle{animation:twinkle 4s ease-in-out infinite}
    .blink{animation:blink 5s ease-in-out infinite}
    .shoot{animation:shoot 12s ease-in infinite;opacity:0}
    .sweep{animation:sweep 5s ease-in-out infinite}
    .beat{animation:beat 3.2s ease-in-out infinite;transform-box:fill-box;transform-origin:center}
    @keyframes fade{from{opacity:0}}
    @keyframes rise{from{opacity:0;transform:translateY(14px)}}
    @keyframes grow{from{transform:scaleX(0)}}
    @keyframes pop{from{opacity:0;transform:scale(.72)}}
    @keyframes glow{0%,100%{opacity:.3}50%{opacity:.8}}
    @keyframes spin{to{transform:rotate(360deg)}}
    @keyframes sway{0%,100%{transform:rotate(-1.8deg)}50%{transform:rotate(1.8deg)}}
    @keyframes float{0%,100%{transform:translateX(0)}50%{transform:translateX(15px)}}
    @keyframes twinkle{0%,100%{opacity:1}50%{opacity:.18}}
    @keyframes blink{0%,100%{opacity:1}42%{opacity:.12}}
    @keyframes shoot{0%{opacity:0;transform:translate(0,0)}3%{opacity:1}13%{opacity:0;transform:translate(330px,175px)}100%{opacity:0;transform:translate(330px,175px)}}
    @keyframes sweep{0%,100%{opacity:.2}50%{opacity:.9}}
    @keyframes beat{0%,100%{transform:scale(1)}50%{transform:scale(1.35)}}
    @media (prefers-reduced-motion:reduce){*{animation:none!important}}
  </style>"""

def _d(seconds):
    """Inline animation-delay attribute fragment."""
    return f' style="animation-delay:{seconds:.2f}s"'

# ============================================================
# ICONS — drawn as paths, never emoji. A README image is rendered with the
# *viewer's* fonts, so an emoji codepoint is a coin toss between colour,
# monochrome and tofu. Every glyph here is geometry, on a 16x16 box.
# ============================================================

def _icon_leaf(color):
    return (f'<path d="M1 15 C1 6 8 1 16 1 C16 9 10 15 1 15 Z" fill="{color}" opacity="0.9"/>'
            f'<path d="M2.5 14.5 C6 11 10.5 7 15 2.5" stroke="{color}" stroke-width="1.1" '
            f'fill="none" opacity="0.45" stroke-linecap="round"/>')

def _icon_brain(color):
    # Two lobes plus folds carved back out in the card colour — at 16px a
    # smooth blob reads as a cloud, the folds are what make it a brain.
    return (f'<path d="M7.5 1.6 C4.4 1.6 2.4 3.4 2.6 5.6 C1 6.6 1 9.2 2.8 10.2 '
            f'C2.6 12.6 5 14.6 7.5 13.8 Z" fill="{color}" opacity="0.92"/>'
            f'<path d="M8.5 1.6 C11.6 1.6 13.6 3.4 13.4 5.6 C15 6.6 15 9.2 13.2 10.2 '
            f'C13.4 12.6 11 14.6 8.5 13.8 Z" fill="{color}" opacity="0.6"/>'
            f'<path d="M5.2 3.8 C6.6 4.8 6.6 6.2 5 7.2 M5.4 9.2 C6.8 9.9 6.8 11.4 5.2 12.2 '
            f'M10.8 3.8 C9.4 4.8 9.4 6.2 11 7.2" stroke="{P["bg_card"]}" stroke-width="1" '
            f'fill="none" stroke-linecap="round"/>')

def _icon_bulb(color):
    return (f'<path d="M8 1 C4.7 1 2.4 3.4 2.4 6.3 C2.4 8.3 3.6 9.6 4.5 10.7 L4.9 12 H11.1 L11.5 10.7 '
            f'C12.4 9.6 13.6 8.3 13.6 6.3 C13.6 3.4 11.3 1 8 1 Z" fill="{color}" opacity="0.9"/>'
            f'<rect x="5.2" y="12.8" width="5.6" height="1.5" rx="0.75" fill="{color}" opacity="0.55"/>'
            f'<rect x="6" y="15" width="4" height="1.4" rx="0.7" fill="{color}" opacity="0.4"/>')

def _icon_quote(color):
    return (f'<path d="M1 13 C1 8 2.6 4.4 6.4 2.6 L7.2 4.4 C5 5.7 4.2 7.2 4.1 8.4 H6.6 V13 Z" fill="{color}"/>'
            f'<path d="M9 13 C9 8 10.6 4.4 14.4 2.6 L15.2 4.4 C13 5.7 12.2 7.2 12.1 8.4 H14.6 V13 Z" fill="{color}"/>')

def _icon_chart(color):
    return (f'<rect x="1" y="9" width="3.6" height="6" rx="1" fill="{color}" opacity="0.55"/>'
            f'<rect x="6.2" y="5" width="3.6" height="10" rx="1" fill="{color}" opacity="0.8"/>'
            f'<rect x="11.4" y="1.5" width="3.6" height="13.5" rx="1" fill="{color}"/>')

def _icon_code(color):
    return (f'<path d="M5.6 3.5 L1 8 L5.6 12.5" stroke="{color}" stroke-width="1.8" fill="none" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
            f'<path d="M10.4 3.5 L15 8 L10.4 12.5" stroke="{color}" stroke-width="1.8" fill="none" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')

def _icon_star_badge(color):
    return (f'<path d="M8 0.8 L10.2 5.6 L15.4 6.2 L11.5 9.8 L12.6 15 L8 12.4 L3.4 15 L4.5 9.8 '
            f'L0.6 6.2 L5.8 5.6 Z" fill="{color}"/>')

CARD_ICONS = {
    "focus": _icon_leaf,
    "mindset": _icon_brain,
    "interests_card": _icon_bulb,
    "quote": _icon_quote,
}

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

# ============================================================
# BRAND MARKS — geometric recreations on a 32x32 box, drawn in the brand
# colour. Anything without a mark falls back to a tinted monogram tile, so
# adding a language to TECH_DB never leaves a hole in the grid.
# ============================================================

def _hexagon(cx, cy, r, **kw):
    pts = " ".join(f"{cx + r*math.cos(math.radians(a)):.1f},{cy + r*math.sin(math.radians(a)):.1f}"
                   for a in range(-90, 270, 60))
    attrs = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in kw.items())
    return f'<polygon points="{pts}" {attrs}/>'

def _mark_javascript(c):
    return (f'<rect x="2" y="2" width="28" height="28" rx="5" fill="{c}"/>'
            f'<text x="16" y="24" text-anchor="middle" font-size="15" font-weight="800" '
            f'fill="#0B1F17" font-family="{MONO}">JS</text>')

def _mark_typescript(c):
    return (f'<rect x="2" y="2" width="28" height="28" rx="5" fill="{c}"/>'
            f'<text x="16" y="24" text-anchor="middle" font-size="15" font-weight="800" '
            f'fill="#FFFFFF" font-family="{MONO}">TS</text>')

def _mark_python(_c):
    blue, yellow = "#4B8BBE", "#FFD343"
    return (f'<path d="M16 2 C10.5 2 10.8 4.6 10.8 4.6 L10.8 8 H16.2 V9 H8.6 C8.6 9 4.8 8.6 4.8 15 '
            f'C4.8 21.4 8.1 21.2 8.1 21.2 H10.2 V17.6 C10.2 17.6 10.1 14.2 13.5 14.2 H18.9 '
            f'C18.9 14.2 22 14.3 22 11.2 V5.2 C22 5.2 22.4 2 16 2 Z" fill="{blue}"/>'
            f'<circle cx="13" cy="5.8" r="1.4" fill="#FFFFFF"/>'
            f'<path d="M16 30 C21.5 30 21.2 27.4 21.2 27.4 L21.2 24 H15.8 V23 H23.4 C23.4 23 27.2 23.4 27.2 17 '
            f'C27.2 10.6 23.9 10.8 23.9 10.8 H21.8 V14.4 C21.8 14.4 21.9 17.8 18.5 17.8 H13.1 '
            f'C13.1 17.8 10 17.7 10 20.8 V26.8 C10 26.8 9.6 30 16 30 Z" fill="{yellow}"/>'
            f'<circle cx="19" cy="26.2" r="1.4" fill="#FFFFFF"/>')

def _mark_java(c):
    return (f'<path d="M13 3 C13 3 10.4 5.6 13.6 8 C16.8 10.4 15.2 12.4 15.2 12.4" stroke="{c}" '
            f'stroke-width="1.6" fill="none" stroke-linecap="round"/>'
            f'<path d="M18.4 5.4 C18.4 5.4 16.6 7.4 19 9.2 C21.4 11 20.2 12.6 20.2 12.6" stroke="{c}" '
            f'stroke-width="1.3" fill="none" opacity="0.6" stroke-linecap="round"/>'
            f'<path d="M8.5 15 H21.5 L20.4 24 C20.2 25.4 19 26.4 17.6 26.4 H12.4 C11 26.4 9.8 25.4 9.6 24 Z" '
            f'fill="{c}"/>'
            f'<path d="M21.8 17 C24.8 17 26 18.4 26 19.8 C26 21.2 24.6 22.2 22.6 22.6" stroke="{c}" '
            f'stroke-width="1.6" fill="none" stroke-linecap="round"/>'
            f'<ellipse cx="15" cy="28.4" rx="9" ry="1.8" fill="{c}" opacity="0.45"/>')

def _mark_hex_text(c, label, size=11):
    return (_hexagon(16, 16, 14, fill=c, opacity="0.95") +
            f'<text x="16" y="{16 + size*0.36:.1f}" text-anchor="middle" font-size="{size}" '
            f'font-weight="800" fill="#08160F" font-family="{MONO}">{label}</text>')

def _mark_shield(c, label):
    return (f'<path d="M5 3 H27 L25 27 L16 30 L7 27 Z" fill="{c}"/>'
            f'<path d="M16 5 V28.2 L23.2 25.6 L24.9 5 Z" fill="#FFFFFF" opacity="0.18"/>'
            f'<text x="16" y="21" text-anchor="middle" font-size="12" font-weight="800" '
            f'fill="#FFFFFF" font-family="{MONO}">{label}</text>')

def _mark_react(c):
    ell = "".join(f'<ellipse cx="16" cy="16" rx="13.5" ry="5.2" fill="none" stroke="{c}" '
                  f'stroke-width="1.5" transform="rotate({a} 16 16)"/>' for a in (0, 60, 120))
    return (f'<g class="spin">{ell}</g><circle cx="16" cy="16" r="2.8" fill="{c}"/>')

def _mark_node(c):
    return (_hexagon(16, 16, 14, fill="none", stroke=c, stroke_width="2") +
            _hexagon(16, 16, 9, fill=c, opacity="0.18") +
            f'<text x="16" y="20" text-anchor="middle" font-size="10" font-weight="800" '
            f'fill="{c}" font-family="{MONO}">JS</text>')

def _mark_git(c):
    return (f'<g transform="rotate(45 16 16)">'
            f'<rect x="4" y="4" width="24" height="24" rx="4" fill="{c}"/>'
            f'<circle cx="11" cy="21" r="2.6" fill="#0B1F17"/>'
            f'<circle cx="21" cy="21" r="2.6" fill="#0B1F17"/>'
            f'<circle cx="21" cy="11" r="2.6" fill="#0B1F17"/>'
            f'<path d="M11 21 H21 V11" stroke="#0B1F17" stroke-width="2" fill="none"/>'
            f'</g>')

def _mark_go(c):
    return (f'<rect x="1" y="8" width="30" height="16" rx="8" fill="{c}" opacity="0.18"/>'
            f'<text x="16" y="21" text-anchor="middle" font-size="13" font-weight="800" '
            f'fill="{c}" font-family="{MONO}">GO</text>')

def _mark_rust(c):
    spokes = "".join(f'<rect x="15" y="1" width="2" height="5" rx="1" fill="{c}" '
                     f'transform="rotate({a} 16 16)"/>' for a in range(0, 360, 45))
    return (spokes +
            f'<circle cx="16" cy="16" r="11" fill="none" stroke="{c}" stroke-width="2"/>'
            f'<text x="16" y="20.5" text-anchor="middle" font-size="12" font-weight="800" '
            f'fill="{c}" font-family="{MONO}">R</text>')

def _mark_docker(c):
    boxes = "".join(f'<rect x="{7 + col*5}" y="{16 - row*5}" width="4.2" height="4.2" rx="0.6" '
                    f'fill="{c}"/>'
                    for col, rows in enumerate((2, 3, 3, 2)) for row in range(rows))
    return (boxes +
            f'<path d="M4 21 H27 C27 25 24 27.5 19 27.5 H11 C7 27.5 4 25 4 21 Z" fill="{c}" opacity="0.85"/>'
            f'<path d="M24 15 C26 13 28.5 14 29 15.6 C27.6 16.6 25.6 16.4 24.6 15.6 Z" fill="{c}" opacity="0.7"/>')

def _mark_monogram(c, label):
    return (f'<rect x="2" y="2" width="28" height="28" rx="8" fill="{c}" opacity="0.16"/>'
            f'<rect x="2" y="2" width="28" height="28" rx="8" fill="none" stroke="{c}" '
            f'stroke-width="1" opacity="0.45"/>'
            f'<text x="16" y="21" text-anchor="middle" font-size="12.5" font-weight="800" '
            f'fill="{c}" font-family="{MONO}">{label}</text>')

BRAND_MARKS = {
    "javascript": _mark_javascript,
    "typescript": _mark_typescript,
    "python":     _mark_python,
    "java":       _mark_java,
    "html":       lambda c: _mark_shield(c, "5"),
    "css":        lambda c: _mark_shield(c, "3"),
    "scss":       lambda c: _mark_shield(c, "S"),
    "sass":       lambda c: _mark_shield(c, "S"),
    "c++":        lambda c: _mark_hex_text(c, "C++", 10),
    "c#":         lambda c: _mark_hex_text(c, "C#", 11),
    "c":          lambda c: _mark_hex_text(c, "C", 13),
    "react":      _mark_react,
    "node.js":    _mark_node,
    "git":        _mark_git,
    "go":         _mark_go,
    "rust":       _mark_rust,
    "docker":     _mark_docker,
}

def _brand_mark(name, color, fallback_label):
    """SVG markup for one 32x32 brand mark, drawn in the brand colour."""
    draw = BRAND_MARKS.get(str(name).strip().lower())
    return draw(color) if draw else _mark_monogram(color, safe_text(fallback_label))

# ============================================================
# SVG GENERATION — Hero Banner
#
# A painted dusk valley: teal sky, cumulus catching the last warm light, a
# ridgeline, a lit town at the horizon, a conifer treeline, and heavy
# foliage framing both upper corners. Everything is vector — no raster, no
# external reference — so it stays a few tens of KB and scales cleanly.
# ============================================================

def _generate_stars_svg(count=26, w=840, h=110, seed=42):
    """A handful of early stars. The sky is bright here, so they are sparse
    and dim; base brightness rides on fill-opacity so they keep their depth
    when the CSS animation is switched off."""
    rng = random.Random(seed)
    stars = []
    for _ in range(count):
        x = rng.randint(0, w)
        y = rng.randint(4, h)
        r = round(rng.uniform(0.4, 1.1), 2)
        op = round(rng.uniform(0.18, 0.6), 2)
        dur = round(rng.uniform(2.5, 7.0), 1)
        delay = round(rng.uniform(0, 6), 1)
        stars.append(
            f'<circle cx="{x}" cy="{y}" r="{r}" fill="#FFF8E4" fill-opacity="{op}" '
            f'class="twinkle" style="animation-duration:{dur}s;animation-delay:{delay}s"/>')
    return "\n    ".join(stars)

def _cloud(x, y, scale, seed, dur, delay):
    """One cumulus: a shadowed body with a lit crown riding on top of it.

    Clouds only breathe sideways a few pixels rather than crossing the sky —
    a full traverse would leave the composition looking different every time
    someone loads the page.
    """
    rng = random.Random(seed)
    base, cx = [], 0.0
    for _ in range(rng.randint(4, 6)):
        r = rng.uniform(15, 27)
        base.append((cx, -rng.uniform(0, 5), r))
        cx += r * rng.uniform(0.78, 1.15)
    right = max(px + pr for px, _, pr in base)

    # A second, smaller tier riding between the base puffs domes the mass;
    # a single row of circles reads as a caterpillar, not a cumulus.
    upper = []
    for i in range(len(base) - 1):
        (x1, _, r1), (x2, _, r2) = base[i], base[i + 1]
        r = (r1 + r2) * 0.5 * rng.uniform(0.55, 0.8)
        upper.append(((x1 + x2) / 2, -(r1 + r2) * 0.5 * rng.uniform(0.45, 0.7), r))
    if len(base) > 2:
        mid = base[len(base) // 2]
        upper.append((mid[0] + rng.uniform(-6, 6), -mid[2] * rng.uniform(0.95, 1.25),
                      mid[2] * rng.uniform(0.5, 0.68)))
    puffs = base + upper

    body = "".join(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{pr:.1f}"/>'
                   for px, py, pr in puffs)
    body += f'<rect x="-8" y="-4" width="{right + 14:.1f}" height="16" rx="8"/>'
    # The light sits low on the horizon, so the crown lifts up and to the left
    crown = "".join(f'<circle cx="{px - 2.5:.1f}" cy="{py - pr * 0.42:.1f}" r="{pr * 0.74:.1f}"/>'
                    for px, py, pr in puffs)

    return (f'<g transform="translate({x},{y}) scale({scale})" filter="url(#cloudSoft)">'
            f'<g class="float" style="animation-duration:{dur}s;animation-delay:{delay}s">'
            f'<g fill="url(#cloudShade)">{body}</g>'
            f'<g fill="url(#cloudLit)">{crown}</g>'
            f'</g></g>')

def _generate_clouds_svg():
    """Cumulus banks: heavy ones stacked at the horizon, wisps higher up."""
    # (x, y, scale, seed, drift seconds, delay)
    specs = [
        (300, 172, 1.90, 3, 46, -8),  (474, 156, 1.45, 9, 38, -21),
        (120, 178, 1.15, 5, 52, -3),  (-34, 150, 0.90, 8, 44, -30),
        (556, 190, 0.85, 12, 58, -14), (226, 104, 0.50, 17, 62, -40),
        (398, 88,  0.42, 21, 34, -19),
    ]
    return "\n    ".join(_cloud(*s) for s in specs)

def _generate_mountains_svg(w=840, base=196, seed=5):
    """Two ridgelines — a hazy far range, a darker near one."""
    rng = random.Random(seed)

    def ridge(y0, amp, step, fill, opacity):
        pts, x = [], -20.0
        while x < w + 20:
            pts.append((x, y0 - rng.uniform(0, amp)))
            x += rng.uniform(step * 0.55, step * 1.5)
        pts.append((w + 20, y0 - rng.uniform(0, amp)))
        d = (f'M{pts[0][0]:.0f} {pts[0][1]:.0f} '
             + " ".join(f'L{px:.0f} {py:.0f}' for px, py in pts[1:]))
        return (f'<path d="{d} L{w + 20} {base + 70} L-20 {base + 70} Z" '
                f'fill="{fill}" opacity="{opacity}"/>')

    return (ridge(base - 8, 26, 78, P["mountain"], "0.55")
            + "\n    " + ridge(base + 4, 15, 54, P["mountain_near"], "0.75"))

def _generate_town_svg(w=840, base_y=236, seed=123):
    """The town at the horizon: low blocks, warm windows, a few of which
    blink so it reads as inhabited rather than printed."""
    rng = random.Random(seed)
    out = []
    lit = ["#FFD79A", "#FFC46B", "#FFEFC7", "#FFB74D"]
    x = 120
    while x < w - 90:
        bw = rng.uniform(7, 17)
        bh = rng.uniform(7, 24)
        y = base_y - bh + rng.uniform(-2.5, 2.5)
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                   f'fill="{P["town"]}" opacity="{rng.uniform(0.34, 0.55):.2f}"/>')
        for row in range(int(bh // 7)):
            for col in range(max(1, int(bw // 6))):
                if rng.random() > 0.55:
                    continue
                wx = x + 2.5 + col * 6
                wy = y + 3 + row * 7
                if wx > x + bw - 2.5:
                    continue
                cls = ""
                if rng.random() > 0.85:
                    cls = (f' class="blink" style="animation-duration:{rng.uniform(3, 9):.1f}s;'
                           f'animation-delay:{rng.uniform(0, 6):.1f}s"')
                out.append(f'<rect x="{wx:.1f}" y="{wy:.1f}" width="2" height="2" '
                           f'fill="{rng.choice(lit)}" fill-opacity="{rng.uniform(0.4, 0.9):.2f}"{cls}/>')
        x += bw + rng.uniform(1.5, 7)
    return "\n    ".join(out)

def _conifer(x, base, h, bw, fill, opacity):
    """A stylised fir, drawn as one zigzag silhouette."""
    d = (f'M{x:.1f} {base - h:.1f} '
         f'L{x + bw*0.22:.1f} {base - h*0.60:.1f} L{x + bw*0.12:.1f} {base - h*0.63:.1f} '
         f'L{x + bw*0.34:.1f} {base - h*0.28:.1f} L{x + bw*0.20:.1f} {base - h*0.31:.1f} '
         f'L{x + bw*0.50:.1f} {base:.1f} L{x - bw*0.50:.1f} {base:.1f} '
         f'L{x - bw*0.20:.1f} {base - h*0.31:.1f} L{x - bw*0.34:.1f} {base - h*0.28:.1f} '
         f'L{x - bw*0.12:.1f} {base - h*0.63:.1f} L{x - bw*0.22:.1f} {base - h*0.60:.1f} Z')
    return f'<path d="{d}" fill="{fill}" opacity="{opacity}"/>'

def _generate_treeline_svg(w=840, base=274, seed=31):
    """The near treeline: a dark band of firs closing off the valley."""
    rng = random.Random(seed)
    out, x = [], -10.0
    while x < w + 10:
        h = rng.uniform(22, 46)
        bw = h * rng.uniform(0.42, 0.66)
        out.append(_conifer(x, base, h, bw, P["tree_mid"], f"{rng.uniform(0.75, 1.0):.2f}"))
        x += bw * rng.uniform(0.34, 0.62)
    # A few tall ones in front for depth
    for tx, th in [(452, 82), (612, 64), (208, 58), (742, 76), (96, 52), (338, 56)]:
        out.append(_conifer(tx, base + 6, th, th * 0.46, P["tree_dark"], "0.96"))
    return "\n    ".join(out)

def _leaf(x, y, rot, scale, fill, opacity):
    return (f'<path transform="translate({x:.1f},{y:.1f}) rotate({rot}) scale({scale})" '
            f'd="M0 0 C7 -9 20 -9 27 0 C20 9 7 9 0 0 Z" fill="{fill}" opacity="{opacity}"/>')

def _bough(ax, ay, branch, reach, drop, count, seed, xdir, delay, scale_lo, scale_hi):
    """One leafy bough anchored to a corner, swaying on a slow loop."""
    rng = random.Random(seed)
    shades = [P["leaf_dark"], P["leaf_mid"], P["leaf_dark"], P["leaf_deep"], P["leaf_hi"]]
    leaves = []
    for i in range(count):
        t = i / max(1, count - 1)
        lx = xdir * (6 + reach * t) + rng.uniform(-16, 16)
        ly = rng.uniform(-6, 10) + drop * t + rng.uniform(-14, 18)
        rot = rng.uniform(-80, 25) * xdir + (180 if rng.random() > 0.5 else 0)
        sc = rng.uniform(scale_lo, scale_hi)
        # The light comes from the horizon, so only a few leaves catch it
        shade = P["leaf_hi"] if rng.random() > 0.88 else rng.choice(shades[:4])
        leaves.append(_leaf(lx, ly, f"{rot:.0f}", f"{sc:.2f}", shade,
                            f"{rng.uniform(0.7, 1.0):.2f}"))
    return (f'<g transform="translate({ax},{ay})">'
            f'<g class="sway" style="transform-origin:{ax}px {ay}px;animation-delay:{delay}s">'
            f'<path d="{branch}" stroke="{P["leaf_dark"]}" stroke-width="3.4" fill="none" '
            f'stroke-linecap="round"/>'
            f'{"".join(leaves)}</g></g>')

def _generate_foliage_svg(w=840):
    """Foliage framing: a heavy bough over the top-left, a lighter one over
    the top-right, and a canopy anchored to the right edge."""
    return "\n    ".join([
        _bough(0, -10, "M-10 0 C70 18 160 34 268 44", 268, 52, 46, 11, 1, 0.0, 0.55, 1.45),
        _bough(0, 34, "M-8 0 C40 22 92 40 150 50", 150, 54, 22, 23, 1, 0.9, 0.5, 1.15),
        _bough(w, -10, "M8 0 C-56 16 -118 32 -186 46", 186, 48, 34, 7, -1, 1.4, 0.5, 1.3),
        _bough(w, 176, "M6 0 C-22 20 -38 50 -46 92", 46, 104, 26, 29, -1, 2.1, 0.6, 1.3),
    ])

def generate_hero_svg(config):
    """Hero banner: a painted dusk valley with the headline set over it."""
    W, H = 840, 300
    BAND_Y = 262                      # dark strip the interest pills sit on

    name = safe_text(fit_text(config.get("name") or "DEVELOPER", 330, 46, bold=True))
    subtitle_raw = fit_text(config.get("hero_subtitle", ""), 520, 15)
    subtitle = safe_text(subtitle_raw)
    side_text = config.get("side_text") or []
    interests = config.get("interests") or []

    # Interest tags, sitting on the dark band
    tags_svg = ""
    tag_x = 34
    for i, interest in enumerate(interests):
        label = fit_text(interest, 130, 11)
        text_len = text_width(label, 11) + 26
        if tag_x + text_len > W - 28:
            break  # Stop if we'd overflow
        tags_svg += (
            f'<g transform="translate({tag_x:.1f},{BAND_Y + 6})">'
            f'<g class="rise"{_d(0.6 + i * 0.09)}>'
            f'<rect width="{text_len:.1f}" height="26" rx="13" '
            f'fill="{P["pill_hero"]}" stroke="{P["pill_edge"]}" stroke-width="1"/>'
            f'<text x="{text_len/2:.1f}" y="17" text-anchor="middle" '
            f'font-size="11" fill="{P["text_bright"]}" font-family="{SANS}">'
            f'{safe_text(label)}</text></g></g>\n    ')
        tag_x += text_len + 10

    # Handwritten margin note, tilted like a scribble in the margin
    side_svg = ""
    lines = [str(x) for x in side_text[:5]]
    for i, word in enumerate(lines):
        label = word.capitalize() if word.isupper() else word
        side_svg += (
            f'<text x="{W - 44}" y="{104 + i * 34}" text-anchor="end" font-size="22" '
            f'fill="{P["gold"]}" opacity="0.9" font-family="{HAND}" '
            f'class="rise"{_d(0.75 + i * 0.12)}>{safe_text(fit_text(label, 210, 22))}</text>\n    ')
    if side_svg:
        # …with the little underline flourish under the last line
        flourish_y = 104 + (len(lines) - 1) * 34 + 12
        side_svg += (f'<path d="M{W - 150} {flourish_y} C{W - 116} {flourish_y + 5}, '
                     f'{W - 82} {flourish_y + 4}, {W - 46} {flourish_y - 2}" '
                     f'stroke="{P["gold"]}" stroke-width="1.4" fill="none" opacity="0.65" '
                     f'stroke-linecap="round" class="fade"{_d(1.25)}/>')
        side_svg = f'<g transform="rotate(-8 {W - 44} 150)">\n    {side_svg}</g>'

    # The subtitle crosses the bright horizon, so it gets its own soft scrim
    sub_w = text_width(subtitle_raw, 15) + 34
    sub_scrim = (f'<rect x="36" y="166" width="{sub_w:.1f}" height="30" rx="15" '
                 f'fill="{P["bg_darkest"]}" opacity="0.42" filter="url(#scrimBlur)"/>'
                 if subtitle_raw else "")

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  {ANIM_CSS}
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0.12" y2="1">
      <stop offset="0%" stop-color="{P["sky_top"]}"/>
      <stop offset="34%" stop-color="{P["sky_mid"]}"/>
      <stop offset="60%" stop-color="{P["sky_haze"]}"/>
      <stop offset="78%" stop-color="{P["sky_horizon"]}"/>
      <stop offset="100%" stop-color="{P["sky_ground"]}"/>
    </linearGradient>
    <linearGradient id="cloudLit" x1="0" y1="0" x2="0.2" y2="1">
      <stop offset="0%" stop-color="{P["cloud_lit"]}"/>
      <stop offset="100%" stop-color="{P["cloud_lit2"]}"/>
    </linearGradient>
    <linearGradient id="cloudShade" x1="0" y1="0" x2="0.2" y2="1">
      <stop offset="0%" stop-color="{P["cloud_shade"]}"/>
      <stop offset="100%" stop-color="{P["cloud_shade2"]}"/>
    </linearGradient>
    <linearGradient id="goldText" x1="0" y1="0" x2="0.5" y2="1">
      <stop offset="0%" stop-color="{P["gold_bright"]}"/>
      <stop offset="55%" stop-color="{P["gold"]}"/>
      <stop offset="100%" stop-color="{P["amber"]}"/>
    </linearGradient>
    <linearGradient id="trail" x1="0" y1="0" x2="1" y2="0.6">
      <stop offset="0%" stop-color="#FFFFFF" stop-opacity="0"/>
      <stop offset="70%" stop-color="#FFF6DF" stop-opacity="0.55"/>
      <stop offset="100%" stop-color="#FFFFFF" stop-opacity="1"/>
    </linearGradient>
    <linearGradient id="bandFade" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{P["band"]}" stop-opacity="0"/>
      <stop offset="55%" stop-color="{P["band"]}" stop-opacity="0.92"/>
      <stop offset="100%" stop-color="{P["band"]}" stop-opacity="1"/>
    </linearGradient>
    <linearGradient id="horizonHaze" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{P["sky_horizon"]}" stop-opacity="0.22"/>
      <stop offset="60%" stop-color="{P["sky_horizon"]}" stop-opacity="0.10"/>
      <stop offset="100%" stop-color="{P["sky_horizon"]}" stop-opacity="0"/>
    </linearGradient>
    <radialGradient id="sunGlow" cx="0.62" cy="0.66" r="0.42">
      <stop offset="0%" stop-color="{P["cloud_lit"]}" stop-opacity="0.38"/>
      <stop offset="100%" stop-color="{P["cloud_lit"]}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="textScrim" cx="0.26" cy="0.44" r="0.55">
      <stop offset="0%" stop-color="{P["bg_darkest"]}" stop-opacity="0.55"/>
      <stop offset="40%" stop-color="{P["bg_darkest"]}" stop-opacity="0.36"/>
      <stop offset="72%" stop-color="{P["bg_darkest"]}" stop-opacity="0.15"/>
      <stop offset="88%" stop-color="{P["bg_darkest"]}" stop-opacity="0.05"/>
      <stop offset="100%" stop-color="{P["bg_darkest"]}" stop-opacity="0"/>
    </radialGradient>
    <filter id="cloudSoft" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="1.7"/>
    </filter>
    <filter id="scrimBlur" x="-15%" y="-60%" width="130%" height="220%">
      <feGaussianBlur stdDeviation="7"/>
    </filter>
    <filter id="textGlow" x="-25%" y="-25%" width="150%" height="150%">
      <feGaussianBlur stdDeviation="5"/>
    </filter>
  </defs>

  <!-- Sky -->
  <rect width="{W}" height="{H}" fill="url(#sky)"/>
  <g>
    {_generate_stars_svg(26, W, 110)}
  </g>
  <rect width="{W}" height="{H}" fill="url(#sunGlow)"/>

  <!-- A meteor crosses every 12s -->
  <g transform="translate(430,4)">
    <g class="shoot">
      <line x1="0" y1="0" x2="96" y2="58" stroke="url(#trail)" stroke-width="1.7"
            stroke-linecap="round"/>
      <circle cx="96" cy="58" r="1.9" fill="#FFFDF4"/>
    </g>
  </g>

  <!-- Clouds -->
  <g>
    {_generate_clouds_svg()}
  </g>

  <!-- Ridgelines, town, treeline -->
  <g>
    {_generate_mountains_svg(W)}
  </g>
  <g>
    {_generate_town_svg(W)}
  </g>
  <rect x="0" y="196" width="{W}" height="48" fill="url(#horizonHaze)"/>
  <g>
    {_generate_treeline_svg(W)}
  </g>

  <!-- Scrim: keeps the headline legible against the bright horizon.
       Soft-edged on every side so it reads as vignetting, not a panel. -->
  <ellipse cx="250" cy="130" rx="360" ry="118" fill="url(#textScrim)"/>
  {sub_scrim}

  <!-- Foliage frame -->
  <g>
    {_generate_foliage_svg(W)}
  </g>

  <!-- Headline -->
  <text x="46" y="96" font-size="22" fill="{P["text_bright"]}" font-family="{SANS}"
        class="fade">Hi there,</text>
  <text x="46" y="150" font-size="46" font-weight="800" fill="{P["gold"]}" opacity="0.45"
        font-family="{SANS}" filter="url(#textGlow)" class="glow"
        >I&#39;m<tspan dx="14">{name}</tspan></text>
  <text x="46" y="150" font-size="46" font-weight="800" font-family="{SANS}"
        class="rise"{_d(0.1)}><tspan fill="url(#goldText)">I&#39;m</tspan><tspan
        dx="14" fill="{P["headline_mint"]}">{name}</tspan></text>
  <text x="46" y="188" font-size="15" fill="{P["text_bright"]}" font-family="{SANS}"
        class="rise"{_d(0.28)}>{subtitle}</text>

  <!-- Handwritten margin note -->
  {side_svg}

  <!-- Dark band the interest tags sit on -->
  <rect x="0" y="{BAND_Y - 16}" width="{W}" height="{H - BAND_Y + 16}" fill="url(#bandFade)"/>
  {tags_svg}
</svg>'''

# ============================================================
# SVG GENERATION — About Cards
# ============================================================

def generate_about_svg(config):
    """Focus / Mindset / Interests / Quote cards, dealt in one by one."""
    cards_cfg = config.get("cards", {})
    quote = config.get("quote", "") or ""   # escaped once, at render time
    W = 840
    card_w = 190
    card_h = 156
    gap = 13
    start_x = (W - (4 * card_w + 3 * gap)) / 2
    H = card_h + 30

    accents = [P["emerald"], P["teal"], P["gold"], P["lime"]]

    def card_frame(x, idx, body):
        accent = accents[idx % len(accents)]
        return f'''
      <g transform="translate({x:.1f},10)">
        <g class="rise"{_d(0.08 * idx)}>
          <rect width="{card_w}" height="{card_h}" rx="12"
                fill="{P["bg_card"]}" stroke="{P["border"]}" stroke-width="0.9"/>
          <rect x="14" y="0" width="{card_w - 28}" height="2" rx="1"
                fill="{accent}" opacity="0.75" class="grow"{_d(0.3 + 0.08 * idx)}/>
          {body(accent)}
        </g>
      </g>'''

    cards_svg = ""
    for idx, key in enumerate(["focus", "mindset", "interests_card"]):
        card = cards_cfg.get(key, {})
        title = card.get("title") or key.replace("_card", "").title()
        items = card.get("items", [])

        def body(accent, key=key, title=title, items=items, idx=idx):
            icon = CARD_ICONS.get(key, _icon_leaf)(accent)
            lines = ""
            for i, item in enumerate(items[:5]):
                lines += (f'<text x="21" y="{74 + i*22}" font-size="12.5" fill="{P["text_primary"]}" '
                          f'font-family="{SANS}" class="fade"{_d(0.45 + 0.08*idx + 0.06*i)}>'
                          f'{safe_text(fit_text(item, card_w - 42, 12.5))}</text>')
            return (f'<g transform="translate(20,26)">{icon}</g>'
                    f'<text x="46" y="39" font-size="14.5" font-weight="700" fill="{accent}" '
                    f'font-family="{SANS}">{safe_text(fit_text(title, card_w - 66, 14.5, bold=True))}</text>'
                    f'{lines}')

        cards_svg += card_frame(start_x + idx * (card_w + gap), idx, body)

    # Quote card
    quote_lines = []
    line_px = card_w - 52
    line = ""
    for word in quote.split():
        candidate = f"{line} {word}".strip()
        if line and text_width(candidate, 12.5, ) > line_px:
            quote_lines.append(line)
            # A single word wider than the card gets trimmed, not overflowed
            line = fit_text(word, line_px, 12.5)
        else:
            line = candidate
    if line:
        quote_lines.append(line)

    def quote_body(accent):
        out = f'<g transform="translate(20,24)">{_icon_quote(accent)}</g>'
        for i, ql in enumerate(quote_lines[:5]):
            out += (f'<text x="21" y="{72 + i*20}" font-size="12.5" fill="{P["text_primary"]}" '
                    f'font-style="italic" font-family="{SANS}" class="fade"{_d(0.65 + 0.06*i)}>'
                    f'{safe_text(ql)}</text>')
        out += (f'<g transform="translate({card_w - 20},{card_h - 22}) rotate(180)" '
                f'opacity="0.45">{_icon_quote(accent)}</g>')
        return out

    cards_svg += card_frame(start_x + 3 * (card_w + gap), 3, quote_body)

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  {ANIM_CSS}
  <rect width="{W}" height="{H}" fill="transparent"/>
  {cards_svg}
</svg>'''

# ============================================================
# SVG GENERATION — Section header
# ============================================================

def _section_header(icon, title, note, w=840, accent=None):
    """Icon + title on the left, a muted note on the right, over a hairline."""
    accent = accent or P["emerald"]
    note_svg = ""
    if note:
        note_svg = (f'<text x="{w - 25}" y="26" text-anchor="end" font-size="10.5" '
                    f'fill="{P["text_muted"]}" font-family="{SANS}" class="fade"{_d(0.35)}>'
                    f'{note}</text>')
    return (f'<g transform="translate(25,10)">{icon(accent)}</g>'
            f'<text x="49" y="27" font-size="17" font-weight="700" fill="{P["text_bright"]}" '
            f'font-family="{SANS}" class="fade">{safe_text(title)}</text>'
            f'{note_svg}'
            f'<rect x="25" y="38" width="{w - 50}" height="1" fill="{P["border"]}" '
            f'class="grow"{_d(0.15)}/>')

# ============================================================
# SVG GENERATION — Tech Stack
# ============================================================

def generate_tech_svg(tech_stack):
    """Tech grid of brand marks. Order follows evidence strength, not taste."""
    W = 840
    all_techs = []
    for cat in ["Languages", "Frameworks", "Databases", "Tools"]:
        all_techs.extend(tech_stack.get(cat, [])[:12])

    if not all_techs:
        return None

    tile_w, tile_h = 76, 78
    cols = min(len(all_techs), 10)
    rows = math.ceil(len(all_techs) / cols)
    gap_x = gap_y = 8
    grid_w = cols * (tile_w + gap_x) - gap_x
    start_x = (W - grid_w) / 2
    H = 58 + rows * (tile_h + gap_y) + 6

    tiles = ""
    for i, tech in enumerate(all_techs):
        x = start_x + (i % cols) * (tile_w + gap_x)
        y = 54 + (i // cols) * (tile_h + gap_y)
        color = tech["color"]
        # Ensure contrast on the dark ground
        if color.upper() in ("#FFFFFF", "#FFF", "#EEEEEE", "#CCCCCC"):
            color = "#C8D6CF"
        label = safe_text(fit_text(tech["name"], tile_w - 10, 9.5))
        tiles += f'''
      <g transform="translate({x:.1f},{y})">
        <g class="pop"{_d(0.1 + i * 0.055)}>
          <rect width="{tile_w}" height="{tile_h}" rx="12" fill="{P["bg_card"]}"
                stroke="{P["border"]}" stroke-width="0.8"/>
          <rect width="{tile_w}" height="{tile_h}" rx="12" fill="{color}" opacity="0.05"/>
          <g transform="translate({(tile_w - 32) / 2},14)">{_brand_mark(tech["name"], color, tech["icon"])}</g>
          <text x="{tile_w / 2}" y="66" text-anchor="middle" font-size="9.5"
                fill="{P["text_secondary"]}" font-family="{SANS}">{label}</text>
        </g>
      </g>'''

    note = f'{len(all_techs)} detected from repo languages &#183; topics'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  {ANIM_CSS}
  <rect width="{W}" height="{H}" fill="transparent"/>
  {_section_header(_icon_code, "Tech Stack", note, W, P["teal"])}
  {tiles}
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
    username = safe_text(fit_text(user_data.get("login", ""), 250, 14, bold=True))

    W, H = 840, 204
    L_X, L_W = 25, 300          # left panel
    R_X, R_W = 345, 470         # right panel
    C_Y, C_H = 50, 145

    rows = [
        ("Public Repositories", fmt_num(user_data.get("public_repos", 0))),
        ("Total Stars Earned",  fmt_num(stats["total_stars"])),
        ("Followers",           fmt_num(user_data.get("followers", 0))),
        ("Following",           fmt_num(user_data.get("following", 0))),
    ]
    rows_svg = ""
    for i, (label, value) in enumerate(rows):
        y = 107 + i * 22        # starts below the divider at y=90 — no overlap
        rows_svg += f'''
      <g class="fade"{_d(0.3 + i * 0.09)}>
        <text x="{L_X + 20}" y="{y}" font-size="12.5" fill="{P["text_secondary"]}"
              font-family="{SANS}">{label}</text>
        <text x="{L_X + L_W - 20}" y="{y}" text-anchor="end" font-size="12.5"
              font-weight="700" fill="{P["gold"]}" font-family="{SANS}">{value}</text>
      </g>'''

    # Language mix — share of non-fork repos whose primary language is X
    langs = stats["top_languages"][:4]
    total_repos_with_lang = sum(c for _, c in stats["top_languages"]) or 1
    max_count = max((c for _, c in langs), default=1) or 1
    bar_x, bar_max = R_X + 118, R_W - 118 - 76
    lang_svg = ""
    for i, (lang, count) in enumerate(langs):
        y = 106 + i * 22
        width = max(5, bar_max * count / max_count)
        pct = 100.0 * count / total_repos_with_lang
        color = TECH_DB.get(lang, {}).get("color", P["emerald"])
        lang_svg += f'''
      <g class="fade"{_d(0.3 + i * 0.09)}>
        <text x="{R_X + 20}" y="{y}" font-size="12" fill="{P["text_secondary"]}"
              font-family="{SANS}">{safe_text(fit_text(lang, 92, 12))}</text>
        <rect x="{bar_x}" y="{y - 9}" width="{bar_max}" height="11" rx="5.5"
              fill="{P["track"]}"/>
        <rect x="{bar_x}" y="{y - 9}" width="{width:.1f}" height="11" rx="5.5"
              fill="{color}" opacity="0.9" class="grow"{_d(0.45 + i * 0.11)}/>
        <text x="{R_X + R_W - 20}" y="{y}" text-anchor="end" font-size="11"
              fill="{P["text_muted"]}" font-family="{SANS}">{pct:.1f}%</text>
      </g>'''

    if not langs:
        lang_svg = f'''
      <text x="{R_X + 20}" y="114" font-size="12" fill="{P["text_muted"]}"
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
  {ANIM_CSS}
  <defs>
    <linearGradient id="panelEdge" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{P["border_glow"]}" stop-opacity="0.8"/>
      <stop offset="100%" stop-color="{P["border"]}" stop-opacity="0.35"/>
    </linearGradient>
  </defs>
  <rect width="{W}" height="{H}" fill="transparent"/>
  {_section_header(_icon_chart, "GitHub Stats", composition, W, P["emerald"])}

  <g class="rise"{_d(0.12)}>
    <rect x="{L_X}" y="{C_Y}" width="{L_W}" height="{C_H}" rx="12"
          fill="{P["bg_card"]}" stroke="url(#panelEdge)" stroke-width="0.9"/>
    <text x="{L_X + 20}" y="{C_Y + 27}" font-size="14" font-weight="700"
          fill="{P["text_bright"]}" font-family="{SANS}">{username}</text>
    <rect x="{L_X + 15}" y="{C_Y + 40}" width="{L_W - 30}" height="1" fill="{P["border"]}"/>
    {rows_svg}
  </g>

  <g class="rise"{_d(0.2)}>
    <rect x="{R_X}" y="{C_Y}" width="{R_W}" height="{C_H}" rx="12"
          fill="{P["bg_card"]}" stroke="url(#panelEdge)" stroke-width="0.9"/>
    <text x="{R_X + 20}" y="{C_Y + 27}" font-size="14" font-weight="700"
          fill="{P["emerald"]}" font-family="{SANS}">Most Used Languages</text>
    <text x="{R_X + R_W - 20}" y="{C_Y + 27}" text-anchor="end" font-size="10"
          fill="{P["text_dim"]}" font-family="{SANS}">share of repos by primary language</text>
    <rect x="{R_X + 15}" y="{C_Y + 40}" width="{R_W - 30}" height="1" fill="{P["border"]}"/>
    {lang_svg}
  </g>
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
        font-family="{SANS}">Contribution activity unavailable</text>
  <text x="{W/2}" y="44" text-anchor="middle" font-size="10" fill="{P["text_dim"]}"
        font-family="{SANS}">{safe_text(reason)}</text>
</svg>'''

def generate_contribution_svg(contribution_data):
    """Contribution calendar, filling in as a wave from January outward."""
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
    # Three clear bands: header (y<=40), month labels (y=44), then the grid.
    start_y = 56
    cells_svg = ""
    month_labels = {}

    for wi, week in enumerate(weeks):
        for day in week.get("contributionDays", []):
            weekday = day.get("weekday", 0)
            count = day.get("contributionCount", 0)
            date_str = day.get("date", "")
            x = start_x + wi * (cell_size + gap)
            y = start_y + weekday * (cell_size + gap)
            delay = 0.15 + wi * 0.011 + weekday * 0.012
            cls = "fade" if count == 0 else "pop"
            cells_svg += (
                f'<rect x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" '
                f'rx="2.5" fill="{get_color(count)}" class="{cls}" '
                f'style="animation-delay:{delay:.2f}s"/>\n    ')
            if date_str and date_str.endswith("-01"):
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    month_labels[x] = dt.strftime("%b")
                except ValueError:
                    pass

    months_svg = ""
    for mx, label in sorted(month_labels.items()):
        months_svg += (
            f'<text x="{mx}" y="{start_y - 8}" font-size="9" fill="{P["text_muted"]}" '
            f'font-family="{SANS}" class="fade">{label}</text>\n    ')

    day_labels_svg = ""
    for i, dname in enumerate(["", "Mon", "", "Wed", "", "Fri", ""]):
        if dname:
            y = start_y + i * (cell_size + gap) + 10
            day_labels_svg += (
                f'<text x="{start_x - 8}" y="{y}" text-anchor="end" font-size="9" '
                f'fill="{P["text_muted"]}" font-family="{SANS}" class="fade">{dname}</text>\n    ')

    H = start_y + 7 * (cell_size + gap) + 26
    legend = "".join(
        f'<rect x="{W - 140 + i*16}" y="{H - 18}" width="{cell_size}" height="{cell_size}" '
        f'rx="2.5" fill="{P[f"contrib_{i}"]}"/>' for i in range(5))

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  {ANIM_CSS}
  <rect width="{W}" height="{H}" fill="transparent"/>
  <g transform="translate(25,8)">{_icon_leaf(P["lime"])}</g>
  <text x="49" y="25" font-size="15" font-weight="700" fill="{P["text_bright"]}"
        font-family="{SANS}" class="fade">{total} contributions in the last year</text>
  <text x="{W - 25}" y="25" text-anchor="end" font-size="10.5" fill="{P["text_muted"]}"
        font-family="{SANS}" class="fade">public activity, rolling 12 months</text>
  <rect x="25" y="36" width="{W - 50}" height="1" fill="{P["border"]}" class="grow"/>
  {months_svg}
  {day_labels_svg}
  {cells_svg}
  <text x="{W - 160}" y="{H - 9}" font-size="9" fill="{P["text_muted"]}"
        font-family="{SANS}">Less</text>
  {legend}
  <text x="{W - 58}" y="{H - 9}" font-size="9" fill="{P["text_muted"]}"
        font-family="{SANS}">More</text>
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

    accents = [P["emerald"], P["teal"], P["gold"], P["lime"], P["sky"], P["amber"]]
    accent = accents[index % len(accents)]

    badge_w = max(44, text_width(badge, 9) + 18)
    name = safe_text(fit_text(raw_name, W - PAD * 2 - badge_w - 10, 15, bold=True))

    # Two description lines instead of one truncated line — GitHub blurbs are
    # usually longer than a single 380px row can hold.
    desc_lines = wrap_text(raw_desc, W - PAD * 2, 12, max_lines=2)
    desc_svg = "".join(
        f'<text x="{PAD}" y="{56 + i * 17}" font-size="12" fill="{P["text_secondary"]}" '
        f'font-family="{SANS}" class="fade"{_d(0.2 + i * 0.07)}>{safe_text(line)}</text>'
        for i, line in enumerate(desc_lines))

    lang_color = TECH_DB.get(lang, {}).get("color", P["text_muted"])
    lang_display = safe_text(fit_text(lang, 150, 11))
    lang_svg = ""
    if lang:
        lang_svg = (
            f'<circle cx="{PAD + 5}" cy="100" r="5" fill="{lang_color}" class="beat"/>'
            f'<text x="{PAD + 16}" y="104" font-size="11" fill="{P["text_secondary"]}" '
            f'font-family="{SANS}">{lang_display}</text>')

    # Stars / forks share the language row, right-aligned — no dead band when
    # a repo has no topics.
    counts_svg = (
        _star_icon(W - 108, 93, P["gold"]) +
        f'<text x="{W - 94}" y="104" font-size="11" fill="{P["text_secondary"]}" '
        f'font-family="{SANS}">{stars}</text>' +
        _fork_icon(W - 60, 94, P["text_muted"]) +
        f'<text x="{W - 44}" y="104" font-size="11" fill="{P["text_secondary"]}" '
        f'font-family="{SANS}">{forks}</text>')

    topics_svg = ""
    tx = PAD
    for i, topic in enumerate(topics if with_topics else []):
        label = fit_text(topic, TOPIC_MAX_PX, 9)
        tw = text_width(label, 9) + 16
        if tx + tw > W - PAD:
            break
        topics_svg += (
            f'<g class="fade"{_d(0.4 + i * 0.08)}>'
            f'<rect x="{tx:.1f}" y="118" width="{tw:.1f}" height="19" rx="9.5" '
            f'fill="{P["pill"]}" stroke="{P["border"]}" stroke-width="0.5"/>'
            f'<text x="{tx + tw / 2:.1f}" y="131" text-anchor="middle" font-size="9" '
            f'fill="{P["text_muted"]}" font-family="{SANS}">{safe_text(label)}</text></g>')
        tx += tw + 5

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  {ANIM_CSS}
  <defs>
    <linearGradient id="cardEdge{index}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{accent}" stop-opacity="0.55"/>
      <stop offset="100%" stop-color="{P["border"]}" stop-opacity="0.25"/>
    </linearGradient>
    <linearGradient id="cardTop{index}" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{accent}" stop-opacity="0.15"/>
      <stop offset="50%" stop-color="{accent}" stop-opacity="0.95"/>
      <stop offset="100%" stop-color="{accent}" stop-opacity="0.15"/>
    </linearGradient>
  </defs>
  <g class="rise">
    <rect x="1" y="1" width="{W-2}" height="{H-2}" rx="12"
          fill="{P["bg_card"]}" stroke="url(#cardEdge{index})" stroke-width="0.9"/>
    <rect x="1" y="1" width="{W-2}" height="2.5" rx="1.25" fill="url(#cardTop{index})"
          class="sweep"/>

    <text x="{PAD}" y="32" font-size="15" font-weight="700" fill="{P["text_bright"]}"
          font-family="{SANS}">{name}</text>
    <rect x="{W - PAD - badge_w:.1f}" y="17" width="{badge_w:.1f}" height="19" rx="9.5"
          fill="{P["pill"]}" stroke="{P["border"]}" stroke-width="0.5"/>
    <text x="{W - PAD - badge_w / 2:.1f}" y="30" text-anchor="middle" font-size="9"
          fill="{P["text_muted"]}" font-family="{SANS}">{safe_text(badge)}</text>

    {desc_svg}
    {lang_svg}
    {counts_svg}
    {topics_svg}
  </g>
</svg>'''

# ============================================================
# SVG GENERATION — Footer
# ============================================================

def generate_footer_svg(config):
    """Closing band: a hairline that breathes, the message, the motto."""
    W, H = 840, 104
    motto = safe_text(fit_text(config.get("motto", ""), W - 220, 10.5))
    message = safe_text(fit_text(config.get("footer_message", ""), W - 200, 13))

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
  {ANIM_CSS}
  <defs>
    <linearGradient id="footerLine" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{P["emerald"]}" stop-opacity="0"/>
      <stop offset="35%" stop-color="{P["emerald"]}" stop-opacity="0.55"/>
      <stop offset="65%" stop-color="{P["gold"]}" stop-opacity="0.5"/>
      <stop offset="100%" stop-color="{P["gold"]}" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect width="{W}" height="{H}" fill="transparent"/>
  <rect x="90" y="14" width="{W - 180}" height="1.4" fill="url(#footerLine)" class="sweep"/>
  <g transform="translate({W/2 - 88},32)">{_icon_leaf(P["lime"])}</g>
  <text x="{W/2 + 10}" y="45" text-anchor="middle" font-size="15" font-weight="700"
        fill="{P["text_bright"]}" font-family="{SANS}" class="rise">Thanks for visiting</text>
  <text x="{W/2}" y="70" text-anchor="middle" font-size="13" fill="{P["emerald"]}"
        font-family="{SANS}" class="rise"{_d(0.12)}>{message}</text>
  <text x="{W/2}" y="92" text-anchor="middle" font-size="10.5" font-style="italic"
        fill="{P["text_muted"]}" font-family="{HAND}" class="fade"{_d(0.3)}>
    &quot;{motto}&quot;</text>
</svg>'''

# ============================================================
# README GENERATION
# ============================================================

SECTION_NAMES = ["HERO", "ABOUT", "TECHSTACK", "STATS",
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
    connect_md = _build_connect_section(config)

    footer = f'''<div align="center">
  <img src="assets/footer.svg" alt="Footer" width="100%"/>
</div>'''

    sections = {
        "HERO": hero,
        "ABOUT": about,
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
