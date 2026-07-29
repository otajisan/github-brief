#!/usr/bin/env python3
"""Aggregate `gh pr list` output into a deterministic bundle + metrics.

This is the deterministic half of the pr-brief loop: every number that appears
in the brief (counts, per-day buckets, change volume, type breakdown) is
computed here, so the model never has to do arithmetic or parse JSON.

usage:
  collect_prs.py \
      --mode weekly --since ISO8601 --until ISO8601 --base main \
      --tz-offset-hours 9 --date-tag 20260729 \
      --html pr-brief-weekly-20260729.html \
      --file merged:owner/repo:/tmp/merged.json \
      --file created:owner/repo:/tmp/created.json \
      --out-bundle bundle.json --out-metrics metrics.json --out-meta meta.json \
      [--prev-metrics prev.json] [--body-max-chars 1200]

Kinds: review (open PRs awaiting review) | merged | created
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

KINDS = ("review", "merged", "created")

# --- PR type classification -------------------------------------------------
# Fixed bucket order. Chart colors are assigned from this order, so a type
# always keeps the same hue across weeks (color follows the entity, not rank).
TYPE_BUCKETS = (
    ("feat", "機能追加・改善"),
    ("fix", "バグ修正"),
    ("refactor", "リファクタ"),
    ("docs", "ドキュメント"),
    ("deps", "依存更新"),
    ("other", "その他"),
)

_CC_PREFIX = {
    "feat": "feat", "feature": "feat", "perf": "feat",
    "fix": "fix", "bugfix": "fix", "hotfix": "fix", "revert": "fix",
    "refactor": "refactor", "style": "refactor",
    "docs": "docs", "doc": "docs",
    "deps": "deps", "dep": "deps",
    "test": "other", "tests": "other", "ci": "other",
    "chore": "other", "build": "other",
}
_CC_RE = re.compile(r"^([a-zA-Z]+)(?:\([^)]*\))?!?:")
_BUMP_RE = re.compile(r"^(bump|update)\b.*\bfrom\b.*\bto\b", re.IGNORECASE)
_BOT_AUTHORS = ("dependabot", "renovate", "github-actions")

_LABEL_HINTS = (
    ("dependenc", "deps"),
    ("deps", "deps"),
    ("documentation", "docs"),
    ("docs", "docs"),
    ("refactor", "refactor"),
    ("enhancement", "feat"),
    ("feature", "feat"),
    ("bug", "fix"),
    ("fix", "fix"),
)

WEEKDAY_JA = ("月", "火", "水", "木", "金", "土", "日")


def classify_type(pr: dict) -> str:
    """Map a PR to one of TYPE_BUCKETS. Deterministic, title/label driven."""
    title = (pr.get("title") or "").strip()
    m = _CC_RE.match(title)
    if m:
        bucket = _CC_PREFIX.get(m.group(1).lower())
        if bucket:
            return bucket

    author = (pr.get("author") or "").lower()
    if any(bot in author for bot in _BOT_AUTHORS) or _BUMP_RE.match(title):
        return "deps"

    labels = " ".join(pr.get("labels") or []).lower()
    for needle, bucket in _LABEL_HINTS:
        if needle in labels:
            return bucket

    if title.lower().startswith("revert"):
        return "fix"
    return "other"


# --- normalization ----------------------------------------------------------
def _iso(value: str | None) -> str | None:
    """gh returns UTC with a trailing Z; make it fromisoformat-safe."""
    if not value:
        return None
    return value[:-1] + "+00:00" if value.endswith("Z") else value


def _truncate(text: str | None, limit: int) -> str:
    body = (text or "").strip()
    if not body or len(body) <= limit:
        return body
    return body[:limit].rstrip() + "\n…(本文は省略)"


def normalize(raw: dict, limit: int) -> dict:
    author = raw.get("author") or {}
    return {
        "number": raw.get("number"),
        "title": raw.get("title") or "",
        "url": raw.get("url") or "",
        "author": author.get("login") or author.get("name") or "unknown",
        "isDraft": bool(raw.get("isDraft")),
        "state": (raw.get("state") or "").upper(),
        "additions": int(raw.get("additions") or 0),
        "deletions": int(raw.get("deletions") or 0),
        "changedFiles": int(raw.get("changedFiles") or 0),
        "labels": [lb.get("name", "") for lb in (raw.get("labels") or [])],
        "createdAt": _iso(raw.get("createdAt")),
        "updatedAt": _iso(raw.get("updatedAt")),
        "mergedAt": _iso(raw.get("mergedAt")),
        "body": _truncate(raw.get("body"), limit),
    }


def load_bundle(args) -> dict:
    """Merge the per-repo gh JSON dumps into one bundle, ordered by repo."""
    per_repo: dict[str, dict[str, list]] = defaultdict(lambda: {k: [] for k in KINDS})
    for spec in args.file:
        kind, rest = spec.split(":", 1)
        repo, path = rest.split(":", 1)
        if kind not in KINDS:
            raise SystemExit(f"unknown kind: {kind} (expected one of {KINDS})")
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh) or []
        current = per_repo[repo][kind]
        seen = {pr["number"] for pr in current}
        per_repo[repo][kind] = current + [
            pr for pr in (normalize(r, args.body_max_chars) for r in raw)
            if pr["number"] not in seen
        ]

    def sort_key(pr: dict) -> str:
        return pr.get("mergedAt") or pr.get("createdAt") or pr.get("updatedAt") or ""

    return {
        "mode": args.mode,
        "since": args.since,
        "until": args.until,
        "base": args.base,
        "tz_offset_hours": args.tz_offset_hours,
        "generated_at": datetime.now(
            timezone(timedelta(hours=args.tz_offset_hours))
        ).isoformat(timespec="seconds"),
        "repos": [
            {
                "repo": repo,
                **{
                    kind: sorted(per_repo[repo][kind], key=sort_key, reverse=True)
                    for kind in KINDS
                },
            }
            for repo in sorted(per_repo)
        ],
    }


# --- metrics ----------------------------------------------------------------
def _day_labels(since: str, until: str, tz_hours: int) -> list[dict]:
    tz = timezone(timedelta(hours=tz_hours))
    start = datetime.fromisoformat(since).astimezone(tz).date()
    end = datetime.fromisoformat(until).astimezone(tz).date()
    return [
        {
            "iso": day.isoformat(),
            "label": day.strftime("%m/%d"),
            "weekday": WEEKDAY_JA[day.weekday()],
        }
        for day in (start + timedelta(days=i)
                    for i in range(max((end - start).days, 0) + 1))
    ]


def _local_date(iso: str | None, tz_hours: int) -> str | None:
    if not iso:
        return None
    tz = timezone(timedelta(hours=tz_hours))
    return datetime.fromisoformat(iso).astimezone(tz).date().isoformat()


def build_metrics(bundle: dict) -> dict:
    tz_hours = bundle["tz_offset_hours"]
    repos = [entry["repo"] for entry in bundle["repos"]]
    merged_all = [
        (entry["repo"], pr) for entry in bundle["repos"] for pr in entry["merged"]
    ]

    per_day: dict[str, Counter] = defaultdict(Counter)
    for repo, pr in merged_all:
        day = _local_date(pr.get("mergedAt"), tz_hours)
        if day:
            per_day[day][repo] += 1

    days = [
        {
            **day,
            "byRepo": dict(per_day.get(day["iso"], {})),
            "total": sum(per_day.get(day["iso"], {}).values()),
        }
        for day in _day_labels(bundle["since"], bundle["until"], tz_hours)
    ]

    by_repo = [
        {
            "key": entry["repo"],
            "label": entry["repo"].split("/")[-1],
            "merged": len(entry["merged"]),
            "created": len(entry["created"]),
            "review": len(entry["review"]),
            "additions": sum(pr["additions"] for pr in entry["merged"]),
            "deletions": sum(pr["deletions"] for pr in entry["merged"]),
        }
        for entry in bundle["repos"]
    ]

    author_counts = Counter(pr["author"] for _, pr in merged_all)
    by_author = [
        {"key": name, "count": count}
        for name, count in sorted(author_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    type_counts = Counter(classify_type(pr) for _, pr in merged_all)
    by_type = [
        {"key": key, "label": label, "count": type_counts.get(key, 0)}
        for key, label in TYPE_BUCKETS
        if type_counts.get(key, 0) > 0
    ]

    kpi = {
        "review": sum(len(entry["review"]) for entry in bundle["repos"]),
        "merged": len(merged_all),
        "created": sum(len(entry["created"]) for entry in bundle["repos"]),
        "additions": sum(pr["additions"] for _, pr in merged_all),
        "deletions": sum(pr["deletions"] for _, pr in merged_all),
        "changedFiles": sum(pr["changedFiles"] for _, pr in merged_all),
        "authors": len(author_counts),
        "repos": len(repos),
    }

    return {
        "mode": bundle["mode"],
        "since": bundle["since"],
        "until": bundle["until"],
        "base": bundle["base"],
        "generated_at": bundle["generated_at"],
        "repos": repos,
        "kpi": kpi,
        "days": days,
        "byRepo": by_repo,
        "byAuthor": by_author,
        "byType": by_type,
    }


def with_delta(metrics: dict, prev_path: str | None) -> dict:
    """Attach a previous-period comparison when a prior metrics file exists."""
    if not prev_path:
        return metrics
    try:
        with open(prev_path, encoding="utf-8") as fh:
            prev = json.load(fh)
    except (OSError, ValueError):
        return metrics
    prev_kpi = prev.get("kpi") or {}
    keys = ("merged", "created", "additions", "deletions")
    return {
        **metrics,
        "delta": {
            "since": prev.get("since"),
            "until": prev.get("until"),
            **{k: metrics["kpi"].get(k, 0) - prev_kpi.get(k, 0) for k in keys},
        },
    }


# --- main -------------------------------------------------------------------
def write_json(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", required=True, choices=("daily", "weekly"))
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--tz-offset-hours", type=int, default=9)
    ap.add_argument("--date-tag", required=True)
    ap.add_argument("--html", required=True, help="basename of the HTML page")
    ap.add_argument("--file", action="append", default=[],
                    metavar="KIND:REPO:PATH", help="gh pr list JSON dump")
    ap.add_argument("--out-bundle", required=True)
    ap.add_argument("--out-metrics", required=True)
    ap.add_argument("--out-meta", required=True)
    ap.add_argument("--prev-metrics")
    ap.add_argument("--body-max-chars", type=int, default=1200)
    args = ap.parse_args()

    bundle = load_bundle(args)
    metrics = with_delta(build_metrics(bundle), args.prev_metrics)

    write_json(args.out_bundle, bundle)
    write_json(args.out_metrics, metrics)
    write_json(args.out_meta, {
        "mode": args.mode,
        "date_tag": args.date_tag,
        "html": args.html,
        "since": args.since,
        "until": args.until,
        "generated_at": bundle["generated_at"],
        "base": args.base,
        "repos": metrics["repos"],
        "counts": {
            "review": metrics["kpi"]["review"],
            "merged": metrics["kpi"]["merged"],
            "created": metrics["kpi"]["created"],
        },
        "additions": metrics["kpi"]["additions"],
        "deletions": metrics["kpi"]["deletions"],
    })

    print(json.dumps({
        "merged": metrics["kpi"]["merged"],
        "created": metrics["kpi"]["created"],
        "review": metrics["kpi"]["review"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
