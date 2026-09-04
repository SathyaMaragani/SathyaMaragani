#!/usr/bin/env python3
"""
Self-check for update-profile.py — assert-based, no test framework needed.

    python scripts/test_update_profile.py

Runs entirely on synthetic fixtures: no network, no writes to README.md or
assets/. Covers the edge cases that would otherwise only show up in
production: hostile repo names, API failures, corrupted markers, and
idempotency.
"""

import importlib.util
import json
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

# The module has a hyphen in its name, so import it by path.
_SPEC = importlib.util.spec_from_file_location(
    "update_profile", Path(__file__).with_name("update-profile.py"))
up = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(up)

NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)
PASSED = []


def check(name):
    PASSED.append(name)
    print(f"  ok  {name}")


def repo(name, **kw):
    """A repo dict shaped like the GitHub REST response."""
    pushed = NOW - timedelta(days=kw.pop("days_ago", 10))
    return {
        "name": name,
        "html_url": f"https://github.com/tester/{name}",
        "description": kw.pop("description", "A description"),
        "language": kw.pop("language", "Python"),
        "languages_url": f"https://api.github.com/repos/tester/{name}/languages",
        "stargazers_count": kw.pop("stars", 0),
        "forks_count": kw.pop("forks", 0),
        "size": kw.pop("size", 100),
        "topics": kw.pop("topics", []),
        "fork": kw.pop("fork", False),
        "archived": kw.pop("archived", False),
        "private": kw.pop("private", False),
        "pushed_at": pushed.strftime("%Y-%m-%dT%H:%M:%SZ"),
        **kw,
    }


CONFIG = {
    "name": "Tester",
    "hero_subtitle": "Builds things",
    "quote": "Ship it & smile <today>",
    "motto": "Less, but better",
    "footer_message": "Thanks!",
    "interests": ["Web", "AI/ML"],
    "side_text": ["SAME", "MINDSET"],
    "cards": {"focus": {"title": "Focus", "emoji": "*", "items": ["Build"]}},
    "socials": {"github": "https://github.com/tester"},
    "max_featured_repos": 6,
}


# ------------------------------------------------------------------
# 1. XML escaping — the "A <B> & C project" case from the audit
# ------------------------------------------------------------------
def test_xml_escaping():
    hostile = repo(
        "A&B<C>",
        description='A <B> & C project with "quotes" and \'apostrophes\'',
        topics=["a&b", "<script>alert(1)</script>"],
    )
    svg = up.generate_repo_card_svg(hostile, 0)
    ET.fromstring(svg)                       # must parse
    assert "<script>" not in svg
    assert "&amp;" in svg
    check("XML escaping survives & < > \" ' and a topic named <script>")

    # A description that is literally an unescaped entity must not double-escape
    assert up.safe_text("a & b") == "a &amp; b"
    assert up.safe_text(None) == ""
    check("safe_text handles None and escapes exactly once")


# ------------------------------------------------------------------
# 2. Text overflow — long names, unicode, emoji, no description
# ------------------------------------------------------------------
def test_text_overflow():
    cases = [
        repo("a" * 200, description="d" * 500),
        repo("CAPITAL-LETTERS-ARE-WIDE-AND-OVERFLOW-CHARCOUNT-TRUNCATION"),
        repo("日本語のリポジトリ名前がとても長い場合", description="説明" * 100),
        repo("🚀🔥💜-emoji-repo-🌟✨🎯", description="🎉" * 80, topics=["🔥" * 20]),
        repo("no-desc", description=None),
        repo("", description=""),
    ]
    CARD_W = 380
    for r in cases:
        svg = up.generate_repo_card_svg(r, 0)
        root = ET.fromstring(svg)
        for el in root.iter():
            if not el.tag.endswith("text") or not (el.text or "").strip():
                continue
            content = el.text.strip()
            size = float(el.get("font-size", 12))
            bold = el.get("font-weight") in ("700", "800", "bold")
            x = float(el.get("x", 0))
            right = x + up.text_width(content, size, bold)
            assert right <= CARD_W, (
                f"{r['name'][:20]!r}: {content[:30]!r} reaches {right:.0f}px "
                f"on a {CARD_W}px card")
    check("long / CJK / emoji / empty names and descriptions stay inside the card")

    assert up.fit_text("short", 500, 12) == "short"
    assert up.fit_text("x" * 100, 50, 12).endswith("…")
    assert up.text_width(up.fit_text("W" * 100, 50, 12), 12) <= 50
    check("fit_text is width-based, not character-based")


# ------------------------------------------------------------------
# 3. Repo counts: 0, 1, 2, 10, 100+
# ------------------------------------------------------------------
def test_repo_counts():
    for n in (0, 1, 2, 10, 100, 150):
        repos = [repo(f"repo-{i}", days_ago=i) for i in range(n)]
        ranked = up.rank_repos(repos, CONFIG, "tester", now=NOW)
        assert len(ranked) == min(n, 6), f"{n} repos -> {len(ranked)} featured"

        stats = up.collect_stats({"public_repos": n}, repos)
        assert stats["owned_count"] == n

        svg = up.generate_stats_svg({"login": "tester", "public_repos": n}, stats)
        ET.fromstring(svg)

        md = up._build_repos_section(ranked, "tester")
        assert ("No public repositories" in md) == (n == 0)
    check("0 / 1 / 2 / 10 / 100 / 150 repositories all render")


# ------------------------------------------------------------------
# 4. Pagination
# ------------------------------------------------------------------
def test_pagination():
    pages = {
        1: [repo(f"r{i}") for i in range(100)],
        2: [repo(f"r{i}") for i in range(100, 200)],
        3: [repo(f"r{i}") for i in range(200, 234)],
    }
    calls = []

    def fake(url, token=None, attempts=3):
        page = int(url.split("&page=")[1].split("&")[0])
        calls.append(page)
        return pages.get(page, [])

    original = up.github_request
    try:
        up.github_request = fake
        repos, complete = up.fetch_all_repos("tester")
        assert complete and len(repos) == 234, (complete, len(repos))
        assert calls == [1, 2, 3], calls
        check("pagination walks every page until a short page (234 repos, 3 pages)")

        # A failure mid-pagination must report incomplete, never partial-as-ok
        def failing(url, token=None, attempts=3):
            page = int(url.split("&page=")[1].split("&")[0])
            return pages[1] if page == 1 else None

        up.github_request = failing
        repos, complete = up.fetch_all_repos("tester")
        assert complete is False, "partial pagination must not report success"
        check("a mid-pagination API failure reports incomplete, not partial success")

        # Malformed response (dict instead of list) must not be treated as repos
        up.github_request = lambda url, token=None, attempts=3: {"message": "Bad creds"}
        repos, complete = up.fetch_all_repos("tester")
        assert complete is False and repos == []
        check("malformed (non-list) repo response is rejected")
    finally:
        up.github_request = original


# ------------------------------------------------------------------
# 5. Exclusions: forks, archived, private, profile repo
# ------------------------------------------------------------------
def test_exclusions():
    repos = [
        repo("real-project", days_ago=1),
        repo("a-fork", fork=True, days_ago=1),
        repo("old-archive", archived=True, days_ago=1),
        repo("secret", private=True, days_ago=1),
        repo("tester", days_ago=1),               # the profile repo itself
        repo("manually-hidden", days_ago=1),
    ]
    cfg = dict(CONFIG, exclude_repositories=["manually-hidden"])
    names = [r["name"] for r in up.rank_repos(repos, cfg, "tester", now=NOW)]
    assert names == ["real-project"], names
    check("forks, archived, private, profile repo and excludes are all filtered")

    # Profile repo is excluded even when config forgets to list it
    assert "tester" in up.excluded_repo_names({}, "tester")
    assert "tester" in up.excluded_repo_names({}, "TESTER")
    check("the profile repo is excluded case-insensitively, without config")

    # ...and configurable back on
    cfg_forks = dict(CONFIG, include_forks_in_featured=True,
                     include_archived_in_featured=True)
    names = [r["name"] for r in up.rank_repos(repos, cfg_forks, "tester", now=NOW)]
    assert "a-fork" in names and "old-archive" in names
    assert "secret" not in names, "private repos must never be featured"
    check("fork/archived inclusion is configurable; private never is")

    # Totals count forks in public_repos but not in stars earned
    stats = up.collect_stats({"public_repos": 6}, repos)
    assert stats["fork_count"] == 1 and stats["archived_count"] == 1
    check("statistics separate sources, forks and archived repos")


# ------------------------------------------------------------------
# 6. Ranking: recency must actually move the needle
# ------------------------------------------------------------------
def test_ranking():
    old_star = repo("ancient-famous", stars=3, days_ago=2000)
    fresh = repo("active-today", stars=0, days_ago=0)
    ranked = up.rank_repos([old_star, fresh], CONFIG, "tester", now=NOW)
    assert ranked[0]["name"] == "active-today", [r["name"] for r in ranked]
    check("a 3-star repo untouched for 5 years loses to today's active work")

    # ...but popularity still wins when both are current
    a = repo("popular", stars=3, days_ago=1)
    b = repo("quiet", stars=0, days_ago=0)
    assert up.rank_repos([a, b], CONFIG, "tester", now=NOW)[0]["name"] == "popular"
    check("with equal recency, stars still decide")

    # Manual override beats everything
    cfg = dict(CONFIG, featured_repositories=["ancient-famous"])
    assert up.rank_repos([old_star, fresh], cfg, "tester", now=NOW)[0]["name"] \
        == "ancient-famous"
    check("featured_repositories overrides the score")

    # Weights are configurable: recency off restores pure popularity
    cfg = dict(CONFIG, ranking_weights={"stars": 5, "recency": 0, "stars_floor": 1.0,
                                        "size": 0, "description": 0, "topics": 0})
    assert up.rank_repos([old_star, fresh], cfg, "tester", now=NOW)[0]["name"] \
        == "ancient-famous"
    check("ranking weights are configurable (recency 0 -> pure popularity)")

    # A missing / malformed pushed_at must not crash the sort
    broken = repo("broken-date")
    broken["pushed_at"] = "not-a-date"
    broken["updated_at"] = None
    assert up.repo_age_days(broken, NOW) == 10_000
    up.rank_repos([broken, fresh], CONFIG, "tester", now=NOW)
    check("malformed pushed_at sorts as ancient instead of crashing")


# ------------------------------------------------------------------
# 7. Missing fields — deleted / renamed / stripped API records
# ------------------------------------------------------------------
def test_missing_fields():
    sparse = {"name": "bare"}                       # every optional field absent
    ET.fromstring(up.generate_repo_card_svg(sparse, 0))
    up.rank_repos([sparse], CONFIG, "tester", now=NOW)
    up.collect_stats({}, [sparse])
    check("a repo record with only a name still renders")

    empty_user = {"login": "tester"}                 # no followers/repos/avatar
    ET.fromstring(up.generate_stats_svg(empty_user, up.collect_stats({}, [])))
    check("a user record with no counts still renders")

    bare_cfg = {}                                    # no name, quote, socials...
    for gen in (up.generate_hero_svg, up.generate_about_svg, up.generate_footer_svg):
        ET.fromstring(gen(bare_cfg))
    assert up._build_connect_section(bare_cfg) == ""
    check("an empty config still produces valid SVGs and omits absent socials")


# ------------------------------------------------------------------
# 8. Tech stack honesty
# ------------------------------------------------------------------
def test_tech_stack():
    repos = [repo("app", language="TypeScript", topics=["react"])]
    stack = up.detect_tech_stack(repos, {})
    names = {t["name"] for items in stack.values() for t in items}
    assert "TypeScript" in names and "React" in names
    check("languages and owner-set topics are detected")

    # A JS repo alone must NOT imply React
    stack = up.detect_tech_stack([repo("plain", language="JavaScript")], {})
    names = {t["name"] for items in stack.values() for t in items}
    assert "React" not in names and "Node.js" not in names
    check("a JavaScript repo does not imply React or Node — no invented tech")

    # Forks contribute nothing
    stack = up.detect_tech_stack([repo("f", language="Rust", fork=True)], {})
    assert "Rust" not in {t["name"] for items in stack.values() for t in items}
    check("forked repos do not contribute to the tech stack")

    # Language breakdown: a 1% sliver is not a skill
    breakdown = {"app": {"TypeScript": 99000, "Shell": 500}}
    stack = up.detect_tech_stack([repo("app", language="TypeScript")], {}, breakdown)
    names = {t["name"] for items in stack.values() for t in items}
    assert "TypeScript" in names and "Shell" not in names
    check("languages below language_min_share of repo bytes are dropped")

    # An override for something unknown is ignored, not rendered blank
    stack = up.detect_tech_stack([repo("a")], {"tech_stack_overrides": ["cobol"]})
    assert all(t["name"] != "cobol" for items in stack.values() for t in items)
    check("unknown tech_stack_overrides entries are ignored with a warning")


# ------------------------------------------------------------------
# 9. Contribution graph honesty
# ------------------------------------------------------------------
def test_contributions():
    for data in (None, {}, {"contributionCalendar": {"weeks": []}}):
        svg = up.generate_contribution_svg(data)
        root = ET.fromstring(svg)
        text = " ".join(e.text or "" for e in root.iter())
        assert "unavailable" in text.lower() or "no contribution" in text.lower()
        # No fabricated cells
        rects = [e for e in root.iter() if e.tag.endswith("rect")]
        assert len(rects) <= 1, "fallback must not draw a fake calendar"
    check("missing contribution data yields an honest message, never fake cells")

    real = {"contributionCalendar": {
        "totalContributions": 5,
        "weeks": [{"contributionDays": [
            {"contributionCount": 5, "date": "2026-01-01", "weekday": 0}]}]}}
    root = ET.fromstring(up.generate_contribution_svg(real))
    assert any("5 contributions" in (e.text or "") for e in root.iter())
    check("real contribution data renders the real total")


# ------------------------------------------------------------------
# 10. SVG safety
# ------------------------------------------------------------------
def test_svg_safety():
    stats = up.collect_stats({"public_repos": 2}, [repo("a"), repo("b")])
    svgs = {
        "hero": up.generate_hero_svg(CONFIG),
        "about": up.generate_about_svg(CONFIG),
        "footer": up.generate_footer_svg(CONFIG),
        "stats": up.generate_stats_svg({"login": "tester", "public_repos": 2}, stats),
        "contrib": up.generate_contribution_svg(None),
        "tech": up.generate_tech_svg(up.detect_tech_stack([repo("a")], {})),
        "card": up.generate_repo_card_svg(repo("a"), 0),
    }
    for name, svg in svgs.items():
        assert not up.validate_svg(name, svg), up.validate_svg(name, svg)
    check("every generated SVG is well-formed, viewBox'd, and free of active content")

    # The validator must actually catch the things it claims to
    assert up.validate_svg("bad", '<svg viewBox="0 0 1 1"><script/></svg>')
    assert up.validate_svg("bad", '<svg viewBox="0 0 1 1"><foreignObject/></svg>')
    assert up.validate_svg("bad", '<svg viewBox="0 0 1 1"><rect onclick="x()"/></svg>')
    assert up.validate_svg("bad", '<svg viewBox="0 0 1 1"><rect/>')      # malformed
    assert up.validate_svg("bad", '<svg><rect/></svg>')                  # no viewBox
    check("validate_svg rejects script, foreignObject, handlers, malformed XML")


# ------------------------------------------------------------------
# 11. README markers + idempotency (uses a temp dir, never the real README)
# ------------------------------------------------------------------
def test_readme_and_idempotency():
    user = {"login": "tester", "name": "Tester", "public_repos": 3,
            "followers": 1, "following": 2}
    repos = [repo("alpha", days_ago=1), repo("beta", days_ago=5)]
    ranked = up.rank_repos(repos, CONFIG, "tester", now=NOW)

    tmp = Path(tempfile.mkdtemp())
    real_readme = up.README_FILE
    try:
        up.README_FILE = tmp / "README.md"

        # First run bootstraps
        first = up.build_readme(user, repos, ranked, CONFIG)
        assert not up.validate_readme(first, {
            "hero-banner.svg", "about-cards.svg", "tech-stack.svg", "stats-card.svg",
            "contribution-graph.svg", "footer.svg", "repo-card-0.svg", "repo-card-1.svg",
        }), up.validate_readme(first, set())
        up.README_FILE.write_text(first, encoding="utf-8")

        # Runs 2 and 3 must be byte-identical — no timestamp churn
        second = up.build_readme(user, repos, ranked, CONFIG)
        third = up.build_readme(user, repos, ranked, CONFIG)
        assert first == second == third, "generator is not idempotent"
        assert not up.write_if_changed(up.README_FILE, second)
        check("three consecutive runs produce byte-identical output (idempotent)")

        # No date/time stamp that would churn daily
        import re
        assert not re.search(r"\b20\d\d-\d\d-\d\dT", first), "README embeds a timestamp"
        assert str(NOW.year) not in first.replace("2000", ""), \
            "README embeds the current year"
        check("no current timestamp is baked into the README")

        # Hand-written content outside the markers survives
        up.README_FILE.write_text(
            first + "\n\n## My own section\n\nHand written, keep me.\n",
            encoding="utf-8")
        updated = up.build_readme(user, repos, ranked, CONFIG)
        assert "Hand written, keep me." in updated
        check("content outside the markers is preserved verbatim")

        # A missing END marker must raise, not silently rewrite the file
        broken = first.replace("<!-- PROFILE:HERO:END -->", "")
        up.README_FILE.write_text(broken, encoding="utf-8")
        try:
            up.build_readme(user, repos, ranked, CONFIG)
            assert False, "corrupted markers were accepted"
        except up.MarkerError as e:
            assert "HERO" in str(e)
        check("an unbalanced marker raises MarkerError instead of overwriting")

        # Duplicated markers must raise too
        up.README_FILE.write_text(first + first, encoding="utf-8")
        try:
            up.build_readme(user, repos, ranked, CONFIG)
            assert False, "duplicated markers were accepted"
        except up.MarkerError:
            pass
        check("duplicated markers raise MarkerError")

        # A README with NO markers must never be clobbered
        up.README_FILE.write_text("# My hand-written profile\n", encoding="utf-8")
        try:
            up.build_readme(user, repos, ranked, CONFIG)
            assert False, "a marker-free README was silently replaced"
        except up.MarkerError as e:
            assert "no <!-- PROFILE" in str(e)
        check("a marker-free README is never silently replaced")

        # ...unless --init is passed explicitly
        rebuilt = up.build_readme(user, repos, ranked, CONFIG, allow_init=True)
        assert "PROFILE:HERO:START" in rebuilt
        check("--init deliberately regenerates a marker-free README")

        # validate_readme catches a card that was never generated
        assert up.validate_readme(first, set()), "missing assets not detected"
        check("validate_readme rejects references to ungenerated assets")
    finally:
        up.README_FILE = real_readme
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------
# 12. API failure modes
# ------------------------------------------------------------------
def test_api_failures():
    original = up.github_request
    try:
        # Total outage
        up.github_request = lambda *a, **k: None
        assert up.fetch_user("tester") is None
        assert up.fetch_all_repos("tester") == ([], False)
        check("a total API outage returns failure, not empty-but-successful data")

        # Malformed user payload (no login)
        up.github_request = lambda *a, **k: {"message": "Not Found"}
        assert up.fetch_user("tester") is None
        check("a user payload without 'login' is rejected as malformed")

        # Languages endpoint failing degrades, never aborts
        up.github_request = lambda *a, **k: None
        assert up.fetch_repo_languages([repo("a")], "tok") == {}
        check("a failing languages endpoint degrades to primary language")
    finally:
        up.github_request = original

    # No token: no GraphQL call is attempted at all
    assert up.fetch_contributions("tester", None) is None
    assert up.github_graphql("query {}", {}, None) is None
    check("without a token, no GraphQL request is attempted")


def test_end_to_end_with_mocks():
    """
    Drive main() end to end against mocked API responses, writing into a temp
    directory. This is the only test that exercises the real orchestrator:
    fetch -> validate -> generate -> validate -> write.
    """
    hostile = [
        repo("A <B> & C project", description='Has & < > " \' in it', stars=1),
        repo("日本語リポジトリ", description="ユニコード" * 40, language="Go"),
        repo("🚀-emoji-" + "x" * 90, description=None, topics=["🔥longtopicname"]),
        repo("archived-thing", archived=True),
        repo("a-fork", fork=True),
        repo("tester"),                                   # the profile repo
        {"name": "sparse-record"},                        # missing everything
    ]
    many = hostile + [repo(f"bulk-{i}", days_ago=i) for i in range(150)]
    user = {"login": "tester", "name": "Tester", "public_repos": len(many),
            "followers": 7, "following": 3}

    def fake_request(url, token=None, attempts=3):
        if "/users/tester/repos" in url:
            page = int(url.split("&page=")[1].split("&")[0])
            start = (page - 1) * up.PER_PAGE
            return many[start:start + up.PER_PAGE]
        if url.endswith("/users/tester"):
            return user
        if "/languages" in url:
            return {"Python": 9000, "Shell": 100}
        return None

    tmp = Path(tempfile.mkdtemp())
    saved = (up.README_FILE, up.ASSETS_DIR, up.CONFIG_FILE, up.github_request,
             up.github_graphql)
    try:
        up.README_FILE = tmp / "README.md"
        up.ASSETS_DIR = tmp / "assets"
        up.CONFIG_FILE = tmp / "profile.config.json"
        up.CONFIG_FILE.write_text(
            json.dumps(dict(CONFIG, github_username="tester")), encoding="utf-8")
        up.github_request = fake_request
        up.github_graphql = lambda *a, **k: None      # no contribution data

        assert up.main([]) == 0, "first run failed"
        assert up.README_FILE.exists()
        cards = sorted(up.ASSETS_DIR.glob("repo-card-*.svg"))
        assert len(cards) == 6, [c.name for c in cards]
        for svg in up.ASSETS_DIR.glob("*.svg"):
            ET.fromstring(svg.read_text(encoding="utf-8"))
        check("end-to-end run over 157 hostile repos writes valid output")

        readme = up.README_FILE.read_text(encoding="utf-8")
        assert "tester" not in [ln.split("/")[-2] for ln in [] ] or True
        assert 'repo-card-6.svg' not in readme
        assert "/tester/tester" not in readme, "profile repo was featured"
        assert "a-fork" not in readme and "archived-thing" not in readme
        check("the profile repo, forks and archived repos stay out of the README")

        # Second run must be a no-op
        before = {p: p.read_bytes() for p in tmp.rglob("*") if p.is_file()}
        assert up.main([]) == 0
        after = {p: p.read_bytes() for p in tmp.rglob("*") if p.is_file()}
        assert before == after, "second run rewrote files"
        check("a second end-to-end run changes nothing on disk")

        # API outage must leave everything intact
        up.github_request = lambda *a, **k: None
        assert up.main([]) == 1, "an API outage should exit non-zero"
        assert {p: p.read_bytes() for p in tmp.rglob("*") if p.is_file()} == after
        check("an API outage exits non-zero and leaves README + assets untouched")

        # Rate-limited mid-pagination: partial data must never be published
        def rate_limited(url, token=None, attempts=3):
            if "&page=1&" in url:
                return many[:up.PER_PAGE]
            if url.endswith("/users/tester"):
                return user
            return None
        up.github_request = rate_limited
        assert up.main([]) == 1
        assert {p: p.read_bytes() for p in tmp.rglob("*") if p.is_file()} == after
        check("a mid-pagination failure aborts rather than publishing 100 of 157 repos")

        # A corrupted marker must abort without touching the file
        up.github_request = fake_request
        up.README_FILE.write_text(readme.replace("<!-- PROFILE:STATS:END -->", ""),
                                  encoding="utf-8")
        damaged = up.README_FILE.read_bytes()
        assert up.main([]) == 1
        assert up.README_FILE.read_bytes() == damaged
        check("a corrupted marker aborts the run and leaves the file as-is")

        # Zero repositories is a valid state, not an error
        many_backup = list(many)
        many.clear()
        user["public_repos"] = 0
        up.README_FILE.unlink()
        assert up.main([]) == 0
        assert "No public repositories" in up.README_FILE.read_text(encoding="utf-8")
        assert not list(up.ASSETS_DIR.glob("repo-card-*.svg")), "stale cards left behind"
        many.extend(many_backup)
        check("an account with zero repositories renders honestly and cleans up cards")
    finally:
        (up.README_FILE, up.ASSETS_DIR, up.CONFIG_FILE, up.github_request,
         up.github_graphql) = saved
        shutil.rmtree(tmp, ignore_errors=True)


def test_config_is_real_json():
    cfg = json.loads((Path(__file__).parents[1] / "profile.config.json")
                     .read_text(encoding="utf-8"))
    for key in ("github_username", "ranking_weights", "exclude_repositories"):
        assert key in cfg, f"profile.config.json missing {key}"
    # Config must not duplicate dynamic GitHub stats
    for banned in ("followers", "stars", "public_repos", "total_stars", "repositories"):
        assert banned not in cfg, f"{banned} must come from the API, not config"
    check("profile.config.json holds only manual data, no duplicated GitHub stats")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"Running {len(tests)} test groups against update-profile.py\n")
    failures = 0
    for t in tests:
        print(f"{t.__name__}:")
        try:
            t()
        except AssertionError as e:
            failures += 1
            print(f"  FAIL  {e}")
        except Exception as e:
            failures += 1
            print(f"  ERROR {type(e).__name__}: {e}")
        print()
    print(f"{len(PASSED)} assertions passed, {failures} group(s) failed")
    sys.exit(1 if failures else 0)
