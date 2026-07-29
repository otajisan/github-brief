#!/usr/bin/env python3
"""Render the weekly release summary as a self-contained HTML fragment.

Reads metrics.json (produced by collect_prs.py) and writes the block that
commands/pr-brief/command.sh splices into the generated page. Every number is
computed upstream in shell — the model never counts and never draws.

Charts: KPI tiles (hero = releases) · 日別リリース数 (stacked column) ·
種別内訳 (100% stacked bar) · リポジトリ別 (bar) · 作者別 (bar).
Each chart ships a table-view twin, so no value is color- or hover-gated.

Marks are plain HTML/CSS rather than SVG on purpose: the cards sit in a
responsive grid, and a scaled SVG viewBox shrinks its own axis labels into
illegibility at narrow widths. CSS bars keep text at real font sizes.

Palette: the validated 8-slot categorical set (checked with the dataviz
validator in both modes — worst adjacent CVD ΔE 9.1 light / 8.4 dark). Light
mode has sub-3:1 slots, so the visible labels and table views are mandatory
relief; do not remove them.

usage: render_charts.py --metrics metrics.json --out charts.html
"""
from __future__ import annotations

import argparse
import html
import json

# --- palette (see references/palette.md of the dataviz skill) ---------------
SERIES_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                "#e87ba4", "#008300", "#4a3aa7", "#e34948")
SERIES_DARK = ("#3987e5", "#d95926", "#199e70", "#c98500",
               "#d55181", "#008300", "#9085e9", "#e66767")
MAX_SLOTS = len(SERIES_LIGHT)

PLOT_H = 200          # px, excludes the x-axis band
AUTHOR_ROWS = 10
OTHER_LABEL = "その他"


def num(value: int | float) -> str:
    return f"{value:,}"


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def pct(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def nice_ticks(top: int, target: int = 4) -> list[int]:
    """Clean axis ticks (1/2/5 × 10ⁿ steps) covering 0..top."""
    if top <= 0:
        return [0, 1]
    step, mult = 1, 1
    while top / step > target:
        for factor in (2, 5, 10):
            step = factor * mult
            if top / step <= target:
                break
        if top / step <= target:
            break
        mult *= 10
    return list(range(0, int(top) + step, step))


def slot(index: int) -> str:
    return f"s{min(index, MAX_SLOTS - 1) + 1}"


# --- shared pieces ----------------------------------------------------------
def legend(items: list[tuple[int, str]]) -> str:
    """Identity is never color-alone: every series also carries a text label."""
    if len(items) < 2:
        return ""
    cells = "".join(
        f'<li><span class="gbc-swatch f-{slot(index)}" aria-hidden="true"></span>'
        f"{esc(text)}</li>"
        for index, text in items
    )
    return f'<ul class="gbc-legend">{cells}</ul>'


def table_view(headers: list[str], rows: list[list[str]], caption: str) -> str:
    head = "".join(f'<th scope="col">{esc(h)}</th>' for h in headers)
    body = "".join(
        "<tr>" + "".join(
            f'<th scope="row">{esc(cell)}</th>' if i == 0 else f"<td>{esc(cell)}</td>"
            for i, cell in enumerate(cells)
        ) + "</tr>"
        for cells in rows
    )
    return (f'<details class="gbc-table"><summary>{esc(caption)}</summary>'
            f'<div class="gbc-scroll"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></details>")


def card(title: str, note: str, inner: str, wide: bool = False) -> str:
    cls = "gbc-card gbc-wide" if wide else "gbc-card"
    sub = f'<p class="gbc-note">{esc(note)}</p>' if note else ""
    return (f'<figure class="{cls}"><figcaption><h3>{esc(title)}</h3>{sub}'
            f"</figcaption>{inner}</figure>")


# --- KPI row ----------------------------------------------------------------
def _delta_text(delta: dict, key: str) -> str:
    """Neutral ink + arrow only: more releases is not automatically 'good'."""
    if key not in delta:
        return ""
    value = delta[key]
    arrow = "±" if value == 0 else ("↑" if value > 0 else "↓")
    return f"前期比 {arrow}{num(abs(value))}"


def kpi_row(metrics: dict) -> str:
    kpi, delta = metrics["kpi"], metrics.get("delta") or {}
    tiles = (
        ("リリース済みPR", num(kpi["merged"]), "件", _delta_text(delta, "merged"), True),
        ("新規作成PR", num(kpi["created"]), "件", _delta_text(delta, "created"), False),
        ("変更行", f"+{num(kpi['additions'])} / −{num(kpi['deletions'])}", "", "", False),
        ("参加した作者", num(kpi["authors"]), "人", "", False),
    )
    cells = []
    for label, value, unit, sub, hero in tiles:
        unit_html = f'<span class="gbc-unit">{esc(unit)}</span>' if unit else ""
        sub_html = f'<p class="gbc-delta">{esc(sub)}</p>' if sub else ""
        cells.append(
            f'<div class="gbc-tile{" gbc-hero" if hero else ""}">'
            f'<p class="gbc-label">{esc(label)}</p>'
            f'<p class="gbc-value">{esc(value)}{unit_html}</p>{sub_html}</div>'
        )
    return f'<div class="gbc-kpi">{"".join(cells)}</div>'


# --- 1. daily releases (stacked column) -------------------------------------
def chart_daily(metrics: dict, slots: dict[str, int]) -> str:
    days = metrics["days"]
    if not days:
        return ""
    ticks = nice_ticks(max(day["total"] for day in days))
    ymax = ticks[-1] or 1

    grid = "".join(
        f'<div class="gbc-gl" style="bottom:{pct(tick / ymax * 100)}%">'
        f'<span class="gbc-ytick">{tick}</span></div>'
        for tick in ticks
    )
    columns = []
    for day in days:
        segments = "".join(
            f'<div class="gbc-seg f-{slot(slots[repo])}" style="flex-grow:{count}" '
            f'title="{esc(f"{day["label"]}({day["weekday"]}) {repo} {count}件")}">'
            "</div>"
            for repo, count in ((r, day["byRepo"].get(r, 0)) for r in slots)
            if count > 0
        )
        total = (f'<span class="gbc-total">{day["total"]}</span>'
                 if day["total"] else "")
        columns.append(
            '<div class="gbc-col">'
            f'<div class="gbc-stack" style="height:{pct(day["total"] / ymax * 100)}%">'
            f"{total}{segments}</div></div>"
        )
    x_axis = "".join(
        f'<div class="gbc-xcell"><span>{esc(day["label"])}</span>'
        f'<span class="gbc-dim">{esc(day["weekday"])}</span></div>'
        for day in days
    )

    keys = list(slots)
    multi = len(keys) > 1
    headers = ["日付"] + ([k.split("/")[-1] for k in keys] if multi else []) + ["合計"]
    rows = [
        [f'{day["label"]}({day["weekday"]})']
        + ([num(day["byRepo"].get(k, 0)) for k in keys] if multi else [])
        + [num(day["total"])]
        for day in days
    ]
    plot = (f'<div class="gbc-plot" role="img" '
            f'aria-label="日別のリリース件数（最大 {ymax}件）">'
            f'{grid}<div class="gbc-cols">{"".join(columns)}</div></div>'
            f'<div class="gbc-xaxis">{x_axis}</div>')
    inner = (legend([(slots[k], k.split("/")[-1]) for k in keys]) + plot
             + table_view(headers, rows, "日別の件数を表で見る"))
    return card("日別リリース数", f'マージ日（{metrics["base"]} へのマージ）で集計',
                inner, wide=True)


# --- 2. type breakdown (100% stacked bar) -----------------------------------
def chart_types(metrics: dict) -> str:
    types = metrics["byType"]
    total = sum(item["count"] for item in types)
    if len(types) < 2 or total == 0:
        return ""
    shares = [round(item["count"] / total * 100) for item in types]
    segments = "".join(
        f'<div class="gbc-sseg f-{slot(i)}" style="flex-grow:{item["count"]}" '
        f'title="{esc(f"{item["label"]} {item["count"]}件（{share}%）")}"></div>'
        for i, (item, share) in enumerate(zip(types, shares))
    )
    bar = (f'<div class="gbc-stacked" role="img" '
           f'aria-label="PR種別の内訳（全{total}件）">{segments}</div>')
    items = [(i, f'{item["label"]} {item["count"]}件（{share}%）')
             for i, (item, share) in enumerate(zip(types, shares))]
    inner = (bar + legend(items)
             + table_view(["種別", "件数", "割合"],
                          [[item["label"], num(item["count"]), f"{share}%"]
                           for item, share in zip(types, shares)],
                          "種別内訳を表で見る"))
    return card("種別内訳",
                "タイトルの Conventional Commits プレフィックスとラベルから自動分類",
                inner, wide=True)


# --- 3/4. horizontal bars ---------------------------------------------------
def chart_bars(title: str, note: str, rows: list[tuple[str, int, str]],
               headers: list[str], caption: str, wide: bool = False) -> str:
    """Nominal categories → one hue for every bar (never a value ramp)."""
    if len(rows) < 2:
        return ""
    top = max(count for _, count, _ in rows) or 1
    body = "".join(
        f'<div class="gbc-row"><span class="gbc-rlabel">{esc(label)}</span>'
        f'<span class="gbc-track"><span class="gbc-fill f-s1" '
        f'style="width:{pct(count / top * 100)}%" title="{esc(tip)}"></span></span>'
        f'<span class="gbc-rvalue">{num(count)}</span></div>'
        for label, count, tip in rows
    )
    plot = (f'<div class="gbc-rows" role="img" '
            f'aria-label="{esc(title)}（最大 {num(top)}件）">{body}</div>')
    inner = plot + table_view(headers,
                              [[label, num(count)] for label, count, _ in rows],
                              caption)
    return card(title, note, inner, wide=wide)


def chart_repos(metrics: dict, wide: bool = False) -> str:
    rows = [
        (item["label"], item["merged"],
         f'{item["key"]} リリース {item["merged"]}件 '
         f'/ +{num(item["additions"])} −{num(item["deletions"])}')
        for item in sorted(metrics["byRepo"], key=lambda i: (-i["merged"], i["key"]))
    ]
    return chart_bars("リポジトリ別リリース数", "期間内にマージされたPR件数",
                      rows, ["リポジトリ", "件数"], "リポジトリ別を表で見る", wide)


def chart_authors(metrics: dict, wide: bool = False) -> str:
    head, tail = metrics["byAuthor"][:AUTHOR_ROWS], metrics["byAuthor"][AUTHOR_ROWS:]
    rows = [(item["key"], item["count"], f'{item["key"]} {item["count"]}件')
            for item in head]
    if tail:
        total = sum(item["count"] for item in tail)
        rows = rows + [(f"{OTHER_LABEL}（{len(tail)}人）", total,
                        f"{OTHER_LABEL} {len(tail)}人 合計 {total}件")]
    note = f"上位{AUTHOR_ROWS}名を表示" if tail else "マージされたPRの作者"
    return chart_bars("作者別リリース数", note, rows, ["作者", "件数"],
                      "作者別を表で見る", wide)


# --- style ------------------------------------------------------------------
def style_block() -> str:
    light = "".join(f"--gbc-s{i + 1}:{c};" for i, c in enumerate(SERIES_LIGHT))
    dark_roles = (
        "--gbc-surface:#1a1a19;--gbc-plane:#0d0d0d;--gbc-ink:#ffffff;"
        "--gbc-ink-2:#c3c2b7;--gbc-muted:#898781;--gbc-grid:#2c2c2a;"
        "--gbc-axis:#383835;--gbc-ring:rgba(255,255,255,.14);"
        + "".join(f"--gbc-s{i + 1}:{c};" for i, c in enumerate(SERIES_DARK))
    )
    fills = "".join(f".gbc .f-s{i + 1}{{background:var(--gbc-s{i + 1})}}"
                    for i in range(MAX_SLOTS))
    return f"""<style>
.gbc{{
  --gbc-surface:#fcfcfb;--gbc-plane:#f4f3ef;--gbc-ink:#0b0b0b;--gbc-ink-2:#52514e;
  --gbc-muted:#898781;--gbc-grid:#e1e0d9;--gbc-axis:#c3c2b7;
  --gbc-ring:rgba(11,11,11,.12);{light}
  color-scheme:light;display:grid;gap:18px;margin:26px 0 34px;color:var(--gbc-ink);
  font-family:system-ui,-apple-system,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif;
}}
@media (prefers-color-scheme:dark){{
  :root:where(:not([data-theme="light"])) .gbc{{color-scheme:dark;{dark_roles}}}
}}
:root[data-theme="dark"] .gbc{{color-scheme:dark;{dark_roles}}}
.gbc *{{box-sizing:border-box}}
.gbc h3{{margin:0;font-size:.95rem;font-weight:650;letter-spacing:.02em;
  color:var(--gbc-ink)}}
.gbc figure{{margin:0}}
.gbc .gbc-note{{margin:4px 0 0;font-size:.72rem;color:var(--gbc-muted)}}

/* KPI tiles */
.gbc-kpi{{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}}
.gbc-tile{{background:var(--gbc-surface);border:1px solid var(--gbc-ring);
  border-radius:14px;padding:14px 16px 16px;display:flex;flex-direction:column}}
.gbc-hero{{grid-column:span 2;background:var(--gbc-plane);border-color:var(--gbc-axis)}}
.gbc-label{{margin:0;font-size:.72rem;letter-spacing:.06em;color:var(--gbc-ink-2)}}
.gbc-value{{margin:2px 0 0;font-size:1.55rem;font-weight:660;line-height:1.15;
  color:var(--gbc-ink)}}
.gbc-hero .gbc-value{{font-size:clamp(2.6rem, 1.7rem + 2.6vw, 3.4rem);
  letter-spacing:-.02em}}
.gbc-unit{{margin-left:.18em;font-size:.62em;font-weight:550;color:var(--gbc-ink-2)}}
.gbc-delta{{margin:6px 0 0;font-size:.74rem;color:var(--gbc-ink-2);
  font-variant-numeric:tabular-nums}}

/* cards */
.gbc-charts{{display:grid;gap:18px;align-items:start;
  grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}}
.gbc-card{{background:var(--gbc-surface);border:1px solid var(--gbc-ring);
  border-radius:16px;padding:18px 20px 14px;display:flex;flex-direction:column;
  gap:14px;min-width:0}}
.gbc-wide{{grid-column:1/-1}}

/* stacked columns */
.gbc-plot{{position:relative;height:{PLOT_H}px;padding-left:34px;margin-top:14px}}
.gbc-gl{{position:absolute;left:34px;right:0;height:0;
  border-top:1px solid var(--gbc-grid)}}
.gbc-gl:first-child{{border-top-color:var(--gbc-axis)}}
.gbc-ytick{{position:absolute;right:calc(100% + 8px);transform:translateY(-50%);
  font-size:11px;color:var(--gbc-muted);font-variant-numeric:tabular-nums}}
.gbc-cols{{position:absolute;inset:0 0 0 34px;display:flex;align-items:flex-end;gap:2px}}
.gbc-col{{flex:1 1 0;display:flex;justify-content:center;align-items:flex-end;
  height:100%}}
.gbc-stack{{position:relative;width:min(24px,62%);display:flex;
  flex-direction:column-reverse;gap:2px;min-height:0}}
.gbc-seg{{flex:1 1 auto;min-height:2px}}
.gbc-seg:last-child{{border-radius:4px 4px 0 0}}
.gbc-total{{position:absolute;bottom:calc(100% + 5px);left:50%;
  transform:translateX(-50%);font-size:12px;font-weight:600;color:var(--gbc-ink);
  font-variant-numeric:tabular-nums}}
.gbc-xaxis{{display:flex;gap:2px;padding-left:34px;margin-top:6px}}
.gbc-xcell{{flex:1 1 0;display:flex;flex-direction:column;align-items:center;
  font-size:11px;color:var(--gbc-muted);font-variant-numeric:tabular-nums}}
.gbc-dim{{font-size:10px;opacity:.85}}

/* 100% stacked bar */
.gbc-stacked{{display:flex;gap:2px;height:30px}}
.gbc-sseg{{flex:1 1 auto;min-width:3px}}
.gbc-sseg:first-child{{border-radius:4px 0 0 4px}}
.gbc-sseg:last-child{{border-radius:0 4px 4px 0}}

/* horizontal bars */
.gbc-rows{{display:grid;gap:9px}}
.gbc-row{{display:grid;grid-template-columns:minmax(56px,26%) 1fr auto;
  align-items:center;gap:10px}}
.gbc-rlabel{{font-size:.78rem;color:var(--gbc-ink-2);text-align:right;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.gbc-track{{display:block;height:18px}}
.gbc-fill{{display:block;height:100%;min-width:2px;border-radius:0 4px 4px 0}}
.gbc-rvalue{{font-size:.78rem;font-weight:600;color:var(--gbc-ink);
  font-variant-numeric:tabular-nums;min-width:2ch;text-align:right}}

/* hover: dim siblings, keep the hovered mark solid */
.gbc-cols:hover .gbc-seg,.gbc-stacked:hover .gbc-sseg,
.gbc-rows:hover .gbc-fill{{opacity:.42;transition:opacity .12s ease}}
.gbc-seg:hover,.gbc-sseg:hover,.gbc-fill:hover{{opacity:1 !important}}

/* legend & table view */
.gbc-legend{{display:flex;flex-wrap:wrap;gap:6px 16px;margin:0;padding:0;
  list-style:none;font-size:.76rem;color:var(--gbc-ink-2)}}
.gbc-legend li{{display:flex;align-items:center;gap:6px}}
.gbc-swatch{{width:10px;height:10px;border-radius:3px;flex:0 0 auto}}
.gbc-table{{margin-top:-2px}}
.gbc-table summary{{cursor:pointer;font-size:.74rem;color:var(--gbc-ink-2);
  padding:2px 0}}
.gbc-scroll{{overflow-x:auto;margin-top:8px}}
.gbc-table table{{border-collapse:collapse;width:100%;font-size:.76rem;
  font-variant-numeric:tabular-nums}}
.gbc-table th,.gbc-table td{{border-bottom:1px solid var(--gbc-grid);
  padding:5px 10px 5px 0;text-align:right;white-space:nowrap;color:var(--gbc-ink)}}
.gbc-table thead th{{color:var(--gbc-ink-2);font-weight:600}}
.gbc-table th:first-child,.gbc-table td:first-child{{text-align:left}}
.gbc-empty{{margin:0;padding:18px 20px;border:1px dashed var(--gbc-axis);
  border-radius:14px;color:var(--gbc-ink-2);font-size:.85rem}}
{fills}
</style>"""


# --- assembly ---------------------------------------------------------------
def repo_slots(metrics: dict) -> dict[str, int]:
    """Assign a color slot per repo by name so a repo keeps its hue over time."""
    return {repo: min(i, MAX_SLOTS - 1)
            for i, repo in enumerate(sorted(metrics["repos"]))}


def render(metrics: dict) -> str:
    if metrics["kpi"]["merged"] == 0:
        charts = (f'<p class="gbc-empty">この期間に {esc(metrics["base"])} へ'
                  "マージされたPRはありません。</p>")
    else:
        slots = repo_slots(metrics)
        # The two bar charts share a row; if only one of them renders (a single
        # repo drops リポジトリ別), give it the full width instead of half a row.
        alone = bool(chart_repos(metrics)) != bool(chart_authors(metrics))
        cards = (chart_daily(metrics, slots), chart_types(metrics),
                 chart_repos(metrics, alone), chart_authors(metrics, alone))
        charts = f'<div class="gbc-charts">{"".join(c for c in cards if c)}</div>'
    return ("<!-- gb:charts:begin -->\n"
            '<section class="gbc" id="release-charts" aria-label="週次リリースサマリ">'
            f"{style_block()}{kpi_row(metrics)}{charts}</section>\n"
            "<!-- gb:charts:end -->\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metrics", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.metrics, encoding="utf-8") as fh:
        metrics = json.load(fh)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(render(metrics))


if __name__ == "__main__":
    main()
