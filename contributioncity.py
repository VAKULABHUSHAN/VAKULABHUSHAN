#!/usr/bin/env python3
"""Contribution City - renders your last year of GitHub contributions as an
isometric 3D city (one building per day) and writes it as a standalone SVG.

Usage:
    python contribution_city.py USERNAME [-o assets/contribution-city.svg]

Data source (first one that works):
    1. GitHub GraphQL API, if GITHUB_TOKEN / GH_TOKEN is set
       (use a PAT with `read:user` to include private-contribution counts)
    2. Public contribution calendar page (no token needed)
Pure standard library - no pip installs.
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import urllib.request

# ---------------------------------------------------------------- data ----

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def _http(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def fetch_graphql(login, token):
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    raw = _http(
        "https://api.github.com/graphql",
        body,
        {"Authorization": f"bearer {token}", "Content-Type": "application/json",
         "User-Agent": "contribution-city"},
    )
    weeks = json.loads(raw)["data"]["user"]["contributionsCollection"][
        "contributionCalendar"]["weeks"]
    return {d["date"]: d["contributionCount"]
            for w in weeks for d in w["contributionDays"]}


def fetch_public(login):
    page = _http(f"https://github.com/users/{login}/contributions",
                 headers={"User-Agent": "contribution-city"})
    dates = dict(re.findall(
        r'data-date="([\d-]+)"\s+id="(contribution-day-component-\d+-\d+)"', page))
    by_id = {v: k for k, v in dates.items()}
    counts = {d: 0 for d in dates}
    for cid, text in re.findall(r'for="(contribution-day-component-\d+-\d+)"[^>]*>([^<]*)<', page):
        m = re.match(r"(\d+) contribution", text.strip())
        if m and cid in by_id:
            counts[by_id[cid]] = int(m.group(1))
    if not counts:
        raise RuntimeError("could not read the public contribution calendar")
    return counts


def load(login):
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        try:
            return fetch_graphql(login, token)
        except Exception as e:  # fall back to the public page
            print(f"GraphQL failed ({e}); falling back to public page")
    return fetch_public(login)


# -------------------------------------------------------------- render ----

# (top, left, right) face colours per level, level 0 = empty ground tile
PALETTE = [
    ("#17706a", "#105a56", "#0b4744"),
    ("#2bb7a6", "#1f9488", "#177a70"),
    ("#3fd0bd", "#2aa99b", "#1e8a7f"),
    ("#6fe3d3", "#3dbfae", "#2a9a8d"),
    ("#b4f7ee", "#63d9c8", "#40b2a4"),
]

W, H = 900, 450
A, B = 10.5, 5.25          # half tile width / half tile height (2:1 isometric)
OX, OY = 312, 96           # screen position of cell (week 0, weekday 0)
MAX_H = 78                 # tallest building in px
GAP = 0.9                  # <1 leaves a thin street between buildings


def level_of(count, vmax):
    if count <= 0:
        return 0
    r = count / vmax
    return 1 if r <= .25 else 2 if r <= .5 else 3 if r <= .75 else 4


def height_of(count, vmax):
    if count <= 0:
        return 2.5
    return 6 + (count / vmax) ** 0.8 * MAX_H


def box(cx, cy, h, colors):
    a, b = A * GAP, B * GAP
    top, left, right = colors
    t = cy - h
    return (
        f'<polygon points="{cx-a:.1f},{t:.1f} {cx:.1f},{t+b:.1f} {cx:.1f},{cy+b:.1f} {cx-a:.1f},{cy:.1f}" fill="{left}"/>'
        f'<polygon points="{cx:.1f},{t+b:.1f} {cx+a:.1f},{t:.1f} {cx+a:.1f},{cy:.1f} {cx:.1f},{cy+b:.1f}" fill="{right}"/>'
        f'<polygon points="{cx:.1f},{t-b:.1f} {cx+a:.1f},{t:.1f} {cx:.1f},{t+b:.1f} {cx-a:.1f},{t:.1f}" fill="{top}"/>'
    )


def short(n):
    return f"{n/1000:.1f}".rstrip("0").rstrip(".") + "K" if n >= 1000 else str(n)


def render(login, counts):
    days = sorted(counts)
    first = dt.date.fromisoformat(days[0])
    start = first - dt.timedelta(days=(first.weekday() + 1) % 7)  # back to Sunday

    cells = []
    for d in days:
        date = dt.date.fromisoformat(d)
        week = (date - start).days // 7
        wd = (date.weekday() + 1) % 7
        cells.append((week, wd, d, counts[d]))

    total = sum(counts.values())
    active = sum(1 for c in counts.values() if c > 0)
    vmax = max(counts.values()) or 1

    out = []
    # back-to-front: cells further along the strip are nearer to the viewer
    for week, wd, d, c in sorted(cells, key=lambda x: (x[0] + x[1], x[0])):
        cx = OX + (week - wd) * A
        cy = OY + (week + wd) * B
        shape = box(cx, cy, height_of(c, vmax), PALETTE[level_of(c, vmax)])
        label = f"{c} contribution{'s' if c != 1 else ''} on {d}"
        out.append(f"<g><title>{label}</title>{shape}</g>")

    f = "'JetBrains Mono','Fira Code',ui-monospace,Menlo,Consolas,monospace"
    s = "'Segoe UI',system-ui,-apple-system,Helvetica,Arial,sans-serif"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Contribution City: {total} contributions in the last year">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#0a3733"/><stop offset=".5" stop-color="#14544f"/><stop offset="1" stop-color="#0a3733"/>
</linearGradient>
</defs>
<rect x="8" y="8" width="{W-16}" height="{H-16}" rx="22" fill="url(#bg)" stroke="#2fb8a5" stroke-opacity=".55" stroke-width="1.5"/>
<text x="42" y="58" font-family="{f}" font-size="11" letter-spacing="4" fill="#5fe0cf" font-weight="700">CONTRIBUTION CITY</text>
<text x="40" y="104" font-family="{s}" font-size="44" font-weight="800" fill="#d9fff9">{short(total)}</text>
<text x="42" y="128" font-family="{s}" font-size="14" fill="#6fe3d3">contributions in the last year</text>
<text x="42" y="158" font-family="{s}" font-size="13" font-weight="600" fill="#6fe3d3">{active} active days</text>
<text x="42" y="178" font-family="{s}" font-size="13" font-weight="600" fill="#6fe3d3">Busiest day: {vmax}</text>
<g>{''.join(out)}</g>
<text x="42" y="{H-48}" font-family="{f}" font-size="12" fill="#6fe3d3">@{html.escape(login.lower())}</text>
<text x="42" y="{H-30}" font-family="{s}" font-size="10" fill="#4bbfae" fill-opacity=".8">updated {dt.date.today().isoformat()}</text>
</svg>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("username")
    ap.add_argument("-o", "--output", default="assets/contribution-city.svg")
    args = ap.parse_args()
    svg = render(args.username, load(args.username))
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"wrote {args.output}")