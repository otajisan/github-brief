#!/usr/bin/env python3
"""Assemble the generated briefs into a small browsable site.

Three deterministic jobs, none of which the model should ever do:

  index   scan OUTPUT_DIR and write index.html — the history hub (latest
          weekly + latest daily up front, then the full archive)
  nav     (re)inject a nav bar into every brief page: back to the hub,
          prev/next of the same mode, and weekly <-> daily cross links so a
          weekly summary can be drilled down into the matching daily briefs
  charts  splice a chart fragment into a freshly generated page

`nav` is idempotent: the block is delimited by gb:nav markers and rebuilt on
every run, so older pages gain links to newer ones.

usage:
  build_site.py index  --output-dir DIR
  build_site.py nav    --output-dir DIR
  build_site.py charts --html page.html --fragment charts.html
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
from datetime import datetime

MODE_JA = {"weekly": "週次", "daily": "日次"}
NAV_BEGIN, NAV_END = "<!-- gb:nav:begin -->", "<!-- gb:nav:end -->"
CHARTS_SLOT = "<!-- gb:charts -->"
NAV_RE = re.compile(re.escape(NAV_BEGIN) + r".*?" + re.escape(NAV_END), re.DOTALL)
CHARTS_RE = re.compile(r"<!-- gb:charts:begin -->.*?<!-- gb:charts:end -->", re.DOTALL)
BODY_RE = re.compile(r"<body\b[^>]*>", re.IGNORECASE)
NAME_RE = re.compile(r"^pr-brief-(daily|weekly)-(\d{8})\.html$")


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


# --- scanning ---------------------------------------------------------------
def _date_label(tag: str) -> str:
    return f"{tag[0:4]}-{tag[4:6]}-{tag[6:8]}"


def _clock(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%m/%d %H:%M")
    except ValueError:
        return ""


def _day(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).date().isoformat()
    except ValueError:
        return None


def window_label(entry: dict) -> str:
    since, until = _clock(entry.get("since")), _clock(entry.get("until"))
    return f"{since} 〜 {until}" if since and until else ""


def scan(output_dir: str) -> list[dict]:
    """All brief pages, newest first. Metadata is optional (older pages lack it)."""
    entries = []
    for path in sorted(glob.glob(os.path.join(output_dir, "pr-brief-*.html"))):
        match = NAME_RE.match(os.path.basename(path))
        if not match:
            continue
        meta_path = path[: -len(".html")] + ".meta.json"
        meta = {}
        if os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
            except (OSError, ValueError):
                meta = {}
        entries.append({
            "mode": match.group(1),
            "date_tag": match.group(2),
            "html": os.path.basename(path),
            "path": path,
            "since": meta.get("since"),
            "until": meta.get("until"),
            "generated_at": meta.get("generated_at"),
            "counts": meta.get("counts") or {},
            "additions": meta.get("additions"),
            "deletions": meta.get("deletions"),
            "repos": meta.get("repos") or [],
            "has_meta": bool(meta),
        })
    return sorted(entries, key=lambda e: (e["date_tag"], e["mode"]), reverse=True)


def by_mode(entries: list[dict], mode: str) -> list[dict]:
    return [entry for entry in entries if entry["mode"] == mode]


def covered_day(entry: dict) -> str:
    """The activity date a page reports on (a daily brief covers the day before)."""
    return _day(entry.get("since")) or _date_label(entry["date_tag"])


def dailies_in_window(entry: dict, dailies: list[dict]) -> list[dict]:
    """Daily briefs whose covered day falls inside this weekly window."""
    start, end = _day(entry.get("since")), _day(entry.get("until"))
    if not start or not end:
        return []
    inside = [daily for daily in dailies if start <= covered_day(daily) <= end]
    return sorted(inside, key=lambda e: e["date_tag"])


def weekly_for_daily(entry: dict, weeklies: list[dict]) -> dict | None:
    day = covered_day(entry)
    for weekly in weeklies:
        start, end = _day(weekly.get("since")), _day(weekly.get("until"))
        if start and end and start <= day <= end:
            return weekly
    return None


# --- nav bar ----------------------------------------------------------------
NAV_CSS = """<style>
.gbn,.gbn-cross{--gbn-surface:#fcfcfb;--gbn-ink:#0b0b0b;--gbn-ink-2:#52514e;
  --gbn-muted:#898781;--gbn-line:rgba(11,11,11,.12);--gbn-accent:#2a78d6;
  font-family:system-ui,-apple-system,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .gbn,
  :root:where(:not([data-theme="light"])) .gbn-cross{--gbn-surface:#1a1a19;
  --gbn-ink:#fff;--gbn-ink-2:#c3c2b7;--gbn-line:rgba(255,255,255,.14);
  --gbn-accent:#3987e5}}
:root[data-theme="dark"] .gbn,:root[data-theme="dark"] .gbn-cross{
  --gbn-surface:#1a1a19;--gbn-ink:#fff;--gbn-ink-2:#c3c2b7;
  --gbn-line:rgba(255,255,255,.14);--gbn-accent:#3987e5}
.gbn{position:sticky;top:0;z-index:99;display:flex;flex-wrap:wrap;align-items:center;
  gap:8px 14px;padding:10px 18px;background:var(--gbn-surface);
  border-bottom:1px solid var(--gbn-line);font-size:.8rem;color:var(--gbn-ink-2)}
.gbn a{color:var(--gbn-accent);text-decoration:none;border-radius:6px;padding:2px 4px}
.gbn a:hover{text-decoration:underline}
.gbn a:focus-visible{outline:2px solid var(--gbn-accent);outline-offset:2px}
.gbn-home{font-weight:650}
.gbn-badge{padding:2px 9px;border-radius:999px;font-size:.72rem;font-weight:650;
  color:var(--gbn-surface);background:var(--gbn-ink)}
.gbn-when{font-variant-numeric:tabular-nums}
.gbn-spacer{flex:1 1 auto}
.gbn-dim{color:var(--gbn-muted)}
.gbn-cross{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;
  padding:8px 18px 10px;border-bottom:1px solid var(--gbn-line);font-size:.76rem;
  color:var(--gbn-ink-2);background:var(--gbn-surface)}
.gbn-cross a{display:inline-block;padding:2px 9px;border:1px solid var(--gbn-line);
  border-radius:999px;color:var(--gbn-ink);text-decoration:none;
  font-variant-numeric:tabular-nums}
.gbn-cross a:hover{border-color:var(--gbn-accent);color:var(--gbn-accent)}
</style>"""


def nav_html(entry: dict, entries: list[dict]) -> str:
    same = by_mode(entries, entry["mode"])          # newest first
    position = next(i for i, e in enumerate(same) if e["html"] == entry["html"])
    newer = same[position - 1] if position > 0 else None
    older = same[position + 1] if position + 1 < len(same) else None
    label = MODE_JA[entry["mode"]]
    window = window_label(entry)

    parts = [
        '<a class="gbn-home" href="index.html">← 履歴一覧</a>',
        f'<span class="gbn-badge">{esc(label)}</span>',
        f'<span class="gbn-when">{esc(_date_label(entry["date_tag"]))}'
        + (f" · {esc(window)}" if window else "") + "</span>",
        '<span class="gbn-spacer"></span>',
        (f'<a href="{esc(older["html"])}">← 前の{esc(label)}'
         f'（{esc(_date_label(older["date_tag"]))}）</a>' if older
         else f'<span class="gbn-dim">← 前の{esc(label)}なし</span>'),
        (f'<a href="{esc(newer["html"])}">次の{esc(label)}'
         f'（{esc(_date_label(newer["date_tag"]))}）→</a>' if newer
         else f'<span class="gbn-dim">次の{esc(label)}なし</span>'),
    ]
    nav = f'<nav class="gbn" aria-label="ブリーフ間ナビゲーション">{"".join(parts)}</nav>'

    cross = ""
    if entry["mode"] == "weekly":
        related = dailies_in_window(entry, by_mode(entries, "daily"))
        if related:
            chips = "".join(
                f'<a href="{esc(daily["html"])}">'
                f'{esc(covered_day(daily)[5:].replace("-", "/"))}分</a>'
                for daily in related
            )
            cross = ('<div class="gbn-cross"><span>この期間の日次ブリーフ:</span>'
                     f"{chips}</div>")
    else:
        weekly = weekly_for_daily(entry, by_mode(entries, "weekly"))
        if weekly:
            cross = ('<div class="gbn-cross"><span>この日を含む週次サマリ:</span>'
                     f'<a href="{esc(weekly["html"])}">'
                     f'{esc(window_label(weekly) or _date_label(weekly["date_tag"]))}'
                     "</a></div>")
    return f"{NAV_BEGIN}{NAV_CSS}{nav}{cross}{NAV_END}"


def inject_nav(entry: dict, entries: list[dict]) -> bool:
    with open(entry["path"], encoding="utf-8") as fh:
        original = fh.read()
    stripped = NAV_RE.sub("", original)
    block = nav_html(entry, entries)
    match = BODY_RE.search(stripped)
    updated = (stripped[: match.end()] + block + stripped[match.end():]
               if match else block + stripped)
    if updated == original:
        return False
    with open(entry["path"], "w", encoding="utf-8") as fh:
        fh.write(updated)
    return True


# --- history hub ------------------------------------------------------------
HUB_CSS = """
*{box-sizing:border-box}
:root{color-scheme:light;--surface:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;
  --ink-2:#52514e;--muted:#898781;--line:#e1e0d9;--ring:rgba(11,11,11,.12);
  --accent:#2a78d6}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){
  color-scheme:dark;--surface:#1a1a19;--plane:#0d0d0d;--ink:#fff;--ink-2:#c3c2b7;
  --muted:#898781;--line:#2c2c2a;--ring:rgba(255,255,255,.14);--accent:#3987e5}}
:root[data-theme="dark"]{color-scheme:dark;--surface:#1a1a19;--plane:#0d0d0d;
  --ink:#fff;--ink-2:#c3c2b7;--line:#2c2c2a;--ring:rgba(255,255,255,.14);
  --accent:#3987e5}
body{margin:0;background:var(--plane);color:var(--ink);line-height:1.6;
  font-family:system-ui,-apple-system,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;
  padding:clamp(28px,4vw,64px) clamp(18px,4vw,40px) 72px}
header{border-bottom:1px solid var(--line);padding-bottom:22px;margin-bottom:30px}
.eyebrow{margin:0;font-size:.72rem;letter-spacing:.22em;text-transform:uppercase;
  color:var(--muted)}
h1{margin:6px 0 8px;font-size:clamp(1.9rem, 1.2rem + 2.4vw, 2.9rem);
  letter-spacing:-.02em;line-height:1.1}
.sub{margin:0;font-size:.84rem;color:var(--ink-2)}
.hero{display:grid;gap:16px;grid-template-columns:1.55fr 1fr;margin-bottom:44px}
@media (max-width:760px){.hero{grid-template-columns:1fr}}
.hero-card{display:flex;flex-direction:column;gap:10px;text-decoration:none;
  color:inherit;background:var(--surface);border:1px solid var(--ring);
  border-radius:18px;padding:22px 24px 20px;
  transition:transform .15s ease,border-color .15s ease,box-shadow .15s ease}
.hero-card:hover{transform:translateY(-2px);border-color:var(--accent);
  box-shadow:0 10px 30px -18px rgba(0,0,0,.45)}
.hero-card:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.kicker{margin:0;font-size:.72rem;letter-spacing:.14em;color:var(--muted)}
.hero-card h2{margin:0;font-size:clamp(1.1rem, .9rem + .8vw, 1.5rem);
  letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.stats{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 18px;margin-top:2px;
  font-size:.82rem;color:var(--ink-2);font-variant-numeric:tabular-nums}
.stats b{font-size:1.5rem;font-weight:660;color:var(--ink);margin-right:.18em}
.cta{margin-top:auto;padding-top:8px;font-size:.8rem;font-weight:650;
  color:var(--accent)}
.empty{background:var(--surface);border:1px dashed var(--ring);border-radius:18px;
  padding:22px 24px;color:var(--ink-2);font-size:.86rem}
.empty code{font-size:.8rem}
h2.section{margin:0 0 4px;font-size:1.05rem;letter-spacing:-.01em}
.archive{display:grid;gap:34px;grid-template-columns:1fr 1fr}
@media (max-width:760px){.archive{grid-template-columns:1fr}}
.month{margin:22px 0 6px;font-size:.72rem;letter-spacing:.16em;color:var(--muted)}
.row{display:grid;grid-template-columns:auto 1fr auto;align-items:baseline;gap:12px;
  padding:9px 4px;border-bottom:1px solid var(--line);text-decoration:none;
  color:inherit}
.row:hover{background:var(--surface)}
.row:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.row time{font-size:.86rem;font-weight:600;font-variant-numeric:tabular-nums}
.win{font-size:.74rem;color:var(--muted);font-variant-numeric:tabular-nums}
.badges{display:flex;gap:8px;font-size:.74rem;color:var(--ink-2);
  font-variant-numeric:tabular-nums;white-space:nowrap}
.badges span{padding:1px 8px;border:1px solid var(--line);border-radius:999px}
footer{margin-top:56px;padding-top:18px;border-top:1px solid var(--line);
  font-size:.74rem;color:var(--muted)}
"""


def _hero(entry: dict | None, mode: str) -> str:
    label = MODE_JA[mode]
    kind = "サマリ" if mode == "weekly" else "ブリーフ"
    if not entry:
        return (f'<div class="empty">まだ{esc(label)}{esc(kind)}がありません。<br>'
                f"<code>github-brief pr-brief {esc(mode)}</code> "
                "を実行するとここに表示されます。</div>")
    counts = entry["counts"]
    if not entry["has_meta"]:
        # Generated before the sidecars existed — there are no numbers to show.
        stats = ['<span class="win">集計データなし</span>']
    elif mode == "weekly":
        stats = [f'<span><b>{esc(counts.get("merged", 0))}</b>リリース</span>',
                 f'<span><b>{esc(counts.get("created", 0))}</b>新規</span>']
    else:
        stats = [f'<span><b>{esc(counts.get("review", 0))}</b>レビュー待ち</span>',
                 f'<span><b>{esc(counts.get("merged", 0))}</b>リリース</span>']
    if entry["has_meta"] and entry.get("additions") is not None:
        stats.append(f'<span>+{entry["additions"]:,} / −{entry["deletions"]:,}</span>')
    return (f'<a class="hero-card" href="{esc(entry["html"])}">'
            f'<p class="kicker">最新の{esc(label)}{esc(kind)}</p>'
            f'<h2>{esc(window_label(entry) or _date_label(entry["date_tag"]))}</h2>'
            f'<div class="stats">{"".join(stats)}</div>'
            f'<span class="cta">開く →</span></a>')


def _rows(entries: list[dict]) -> str:
    out, current_month = [], None
    for entry in entries:
        month = f'{entry["date_tag"][0:4]}年{int(entry["date_tag"][4:6])}月'
        if month != current_month:
            out.append(f'<p class="month">{esc(month)}</p>')
            current_month = month
        counts = entry["counts"]
        if not entry["has_meta"]:
            badges = ['<span class="win">集計データなし</span>']
        elif entry["mode"] == "weekly":
            badges = [f'<span>🚀 {esc(counts.get("merged", "–"))}</span>',
                      f'<span>🆕 {esc(counts.get("created", "–"))}</span>']
        else:
            badges = [f'<span>🔍 {esc(counts.get("review", "–"))}</span>',
                      f'<span>🚀 {esc(counts.get("merged", "–"))}</span>']
        out.append(
            f'<a class="row" href="{esc(entry["html"])}">'
            f'<time datetime="{esc(_date_label(entry["date_tag"]))}">'
            f'{esc(_date_label(entry["date_tag"])[5:])}</time>'
            f'<span class="win">{esc(window_label(entry))}</span>'
            f'<span class="badges">{"".join(badges)}</span></a>'
        )
    return "".join(out) or '<p class="win">まだありません</p>'


def build_index(output_dir: str) -> str:
    entries = scan(output_dir)
    weeklies, dailies = by_mode(entries, "weekly"), by_mode(entries, "daily")
    repos = next((e["repos"] for e in entries if e["repos"]), [])
    updated = next((_clock(e["generated_at"]) for e in entries if e["generated_at"]), "")
    subtitle = " · ".join(filter(None, [
        f"最終更新 {updated}" if updated else "",
        "対象: " + ", ".join(repos) if repos else "",
        f"週次 {len(weeklies)}件 / 日次 {len(dailies)}件",
    ]))
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>github-brief — アクティビティ履歴</title>
<style>{HUB_CSS}</style>
</head>
<body>
<div class="wrap">
<header>
  <p class="eyebrow">github-brief</p>
  <h1>アクティビティ履歴</h1>
  <p class="sub">{esc(subtitle)}</p>
</header>

<section class="hero" aria-label="最新のブリーフ">
{_hero(weeklies[0] if weeklies else None, "weekly")}
{_hero(dailies[0] if dailies else None, "daily")}
</section>

<section class="archive">
  <div>
    <h2 class="section">週次サマリ</h2>
    <p class="sub">定例MTG用。リリース内容の全体像。</p>
    {_rows(weeklies)}
  </div>
  <div>
    <h2 class="section">日次ブリーフ</h2>
    <p class="sub">週次から掘り下げるとき用。レビュー待ちと当日リリース。</p>
    {_rows(dailies)}
  </div>
</section>

<footer>このページは github-brief が自動生成しています。</footer>
</div>
</body>
</html>
"""


# --- chart injection --------------------------------------------------------
def inject_charts(html_path: str, fragment_path: str) -> str:
    with open(html_path, encoding="utf-8") as fh:
        page = fh.read()
    with open(fragment_path, encoding="utf-8") as fh:
        fragment = fh.read()

    # A stale fragment folds back into its marker, so a re-run lands in the
    # same place instead of drifting to the top of the document.
    page = CHARTS_RE.sub(CHARTS_SLOT, page)
    if CHARTS_SLOT in page:
        return _write(html_path, page.replace(CHARTS_SLOT, fragment, 1)) or "slot"
    match = BODY_RE.search(page)
    if match:
        return _write(html_path,
                      page[: match.end()] + fragment + page[match.end():]) or "body"
    return _write(html_path, fragment + page) or "prepend"


def _write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


# --- main -------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser("index", help="write index.html (history hub)")
    p_index.add_argument("--output-dir", required=True)

    p_nav = sub.add_parser("nav", help="(re)inject the nav bar into brief pages")
    p_nav.add_argument("--output-dir", required=True)

    p_charts = sub.add_parser("charts", help="splice a chart fragment into a page")
    p_charts.add_argument("--html", required=True)
    p_charts.add_argument("--fragment", required=True)

    args = ap.parse_args()

    if args.cmd == "index":
        target = os.path.join(args.output_dir, "index.html")
        _write(target, build_index(args.output_dir))
        print(f"index: {target}")
    elif args.cmd == "nav":
        entries = scan(args.output_dir)
        changed = sum(inject_nav(entry, entries) for entry in entries)
        print(f"nav: {changed}/{len(entries)} page(s) updated")
    else:
        print(f"charts: injected ({inject_charts(args.html, args.fragment)})")


if __name__ == "__main__":
    main()
