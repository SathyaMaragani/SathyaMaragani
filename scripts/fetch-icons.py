#!/usr/bin/env python3
"""
Vendor real icons into assets/icons/ so the profile generator never has to
invent a logo, and never depends on a third-party URL at render time.

    python scripts/fetch-icons.py

Sources, in order of preference:
  Simple Icons  — CC0-1.0, one path per brand, official brand colour.
  Devicon       — MIT, used only where Simple Icons has no entry.
  Octicons      — MIT, GitHub's own UI set, for the non-brand glyphs.

Run this only when adding a technology or refreshing the set; the daily
profile workflow reads the committed JSON and makes no network call for
icons. Anything that cannot be fetched is simply absent from the JSON, and
the generator falls back to a clean text label rather than a drawn shape.
"""

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "assets" / "icons"

SIMPLE_ICONS = "https://cdn.jsdelivr.net/npm/simple-icons@15/icons/{slug}.svg"
SIMPLE_DATA = "https://cdn.jsdelivr.net/npm/simple-icons@15/data/simple-icons.json"
DEVICON = "https://cdn.jsdelivr.net/gh/devicons/devicon@v2.16.0/icons/{slug}/{slug}-original.svg"
OCTICON = "https://cdn.jsdelivr.net/npm/@primer/octicons@19/build/svg/{slug}-24.svg"

# Display name (must match TECH_DB in update-profile.py) -> Simple Icons slug.
SIMPLE_SLUGS = {
    "JavaScript": "javascript", "TypeScript": "typescript", "Python": "python",
    "HTML": "html5", "CSS": "css", "Java": "java", "C++": "cplusplus",
    "C#": "csharp", "C": "c", "Go": "go", "Rust": "rust", "Ruby": "ruby",
    "PHP": "php", "Swift": "swift", "Kotlin": "kotlin", "Dart": "dart",
    "Shell": "gnubash", "Lua": "lua", "Scala": "scala", "SCSS": "sass",
    "Sass": "sass", "EJS": "ejs", "Jupyter Notebook": "jupyter",
    "PowerShell": "powershell", "Vue": "vuedotjs", "Svelte": "svelte",
    "React": "react", "Next.js": "nextdotjs", "Node.js": "nodedotjs",
    "Express": "express", "Django": "django", "Flask": "flask",
    "FastAPI": "fastapi", "Angular": "angular", "Tailwind": "tailwindcss",
    "Bootstrap": "bootstrap", "Flutter": "flutter", "Vite": "vite",
    "Electron": "electron", "Three.js": "threedotjs",
    "PostgreSQL": "postgresql", "MongoDB": "mongodb", "MySQL": "mysql",
    "Redis": "redis", "SQLite": "sqlite", "Firebase": "firebase",
    "Supabase": "supabase", "Prisma": "prisma", "Docker": "docker",
    "Kubernetes": "kubernetes", "Git": "git", "GitHub Actions": "githubactions",
    "AWS": "amazonwebservices", "Vercel": "vercel", "Netlify": "netlify",
    "Linux": "linux",
    # Social destinations, used by the connect row rather than the tech grid
    "LinkedIn": "linkedin", "X": "x",
}

# Taken from Devicon regardless of what Simple Icons offers.
FORCE_DEVICON = {"CSS": "css3"}

# Fallbacks for anything Simple Icons has dropped or never carried.
DEVICON_SLUGS = {"Java": "java", "C": "c", "C++": "cplusplus", "C#": "csharp",
                 "PowerShell": "powershell", "AWS": "amazonwebservices",
                 "LinkedIn": "linkedin"}

# GitHub's own UI set, for section headers and metadata rows.
OCTICON_NAMES = [
    "goal", "light-bulb", "quote", "code", "graph", "star", "star-fill",
    "repo", "repo-forked", "git-branch", "git-commit", "git-pull-request",
    "issue-opened", "flame", "calendar", "location", "link", "mail",
    "mark-github", "person", "telescope", "rocket", "zap", "heart",
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "profile-icon-vendor"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def svg_body(svg):
    """Inner markup of an <svg>, with <title>/comments stripped."""
    inner = re.sub(r"^.*?<svg[^>]*>|</svg>\s*$", "", svg, flags=re.DOTALL)
    inner = re.sub(r"<title>.*?</title>", "", inner, flags=re.DOTALL)
    inner = re.sub(r"<!--.*?-->", "", inner, flags=re.DOTALL)
    return " ".join(inner.split())


def view_box(svg, default="0 0 24 24"):
    m = re.search(r'viewBox="([^"]+)"', svg)
    return m.group(1) if m else default


def main():
    ICON_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching Simple Icons brand colours...")
    try:
        raw = json.loads(fetch(SIMPLE_DATA))
        entries = raw["icons"] if isinstance(raw, dict) else raw
        colors = {e["title"]: "#" + e["hex"] for e in entries}
    except Exception as e:                       # colours are a nicety, not a blocker
        print(f"  ! colour table unavailable ({e}); falling back to per-icon defaults")
        colors = {}

    tech, missing = {}, []
    for name, slug in SIMPLE_SLUGS.items():
        svg = None
        if name not in FORCE_DEVICON:
            try:
                svg = fetch(SIMPLE_ICONS.format(slug=slug))
            except urllib.error.HTTPError:
                svg = None
        if svg:
            title = re.search(r"<title>(.*?)</title>", svg)
            tech[name] = {
                "viewBox": view_box(svg),
                "body": svg_body(svg),
                "color": colors.get(title.group(1) if title else "", ""),
                "mono": True,
                "source": "Simple Icons (CC0-1.0)",
            }
            print(f"  simple-icons  {name}")
            continue

        dev = FORCE_DEVICON.get(name) or DEVICON_SLUGS.get(name)
        if dev:
            try:
                svg = fetch(DEVICON.format(slug=dev))
                tech[name] = {
                    "viewBox": view_box(svg, "0 0 128 128"),
                    "body": svg_body(svg),
                    "color": "",
                    "mono": False,          # devicon originals carry their own fills
                    "source": "Devicon (MIT)",
                }
                print(f"  devicon       {name}")
                continue
            except urllib.error.HTTPError:
                pass
        missing.append(name)

    ui = {}
    for name in OCTICON_NAMES:
        try:
            svg = fetch(OCTICON.format(slug=name))
        except urllib.error.HTTPError:
            missing.append(f"octicon:{name}")
            continue
        ui[name] = {"viewBox": view_box(svg), "body": svg_body(svg),
                    "mono": True, "source": "Octicons (MIT)"}
        print(f"  octicons      {name}")

    (ICON_DIR / "tech-icons.json").write_text(
        json.dumps(tech, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (ICON_DIR / "ui-icons.json").write_text(
        json.dumps(ui, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (ICON_DIR / "NOTICE.md").write_text(NOTICE, encoding="utf-8", newline="\n")

    print(f"\n{len(tech)} technology icons, {len(ui)} UI icons -> {ICON_DIR}")
    if missing:
        print("Not available (the generator will use a text label instead):")
        for m in sorted(missing):
            print(f"  - {m}")
    return 0


NOTICE = """# Icon attributions

Icons in `tech-icons.json` and `ui-icons.json` are vendored by
`scripts/fetch-icons.py`. They are stored here rather than hot-linked so the
profile never depends on a third-party URL at render time.

| Set | Licence | Used for |
|---|---|---|
| [Simple Icons](https://github.com/simple-icons/simple-icons) | CC0-1.0 | Technology brand marks |
| [Devicon](https://github.com/devicons/devicon) | MIT | Brand marks Simple Icons does not carry |
| [Octicons](https://github.com/primer/octicons) | MIT | GitHub's own UI glyphs |

Brand marks remain the property of their respective owners and are used here
to identify the technology, not to imply endorsement.
"""

if __name__ == "__main__":
    sys.exit(main())
