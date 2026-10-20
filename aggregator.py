#!/usr/bin/env python3
# Watermark: Living_Sin (intricos777-dot) + AI agents (Hermes, Lia, opencode) - collaborative work
"""
The Seeker's Lens — Micro-task & Survey Aggregator
=================================================
Watches public feeds for new paid studies/micro-tasks and alerts you
to high-value opportunities so you can claim them fast.

Sources (all free, no account needed to WATCH):
  * Reddit r/beermoney   — https://www.reddit.com/r/beermoney/new/.rss
  * Reddit r/WorkOnline  — https://www.reddit.com/r/WorkOnline/new/.rss
  * Reddit r/slavelabour — https://www.reddit.com/r/slavelabour/new/.rss
  (These communities post paid studies, micro-task gigs, and user-testing
  opportunities around the clock. Prolific's own feed now requires a
  logged-in session, so it's disabled by default but easy to re-add.)

Usage:
  python3 aggregator.py                # one-shot scan
  python3 aggregator.py --watch 5      # scan every 5 minutes
  python3 aggregator.py --threshold 2  # only report studies >= $2
  python3 aggregator.py --history      # show seen items

The script keeps a local cache so you only get NEW opportunities,
never repeats. Optionally sends a desktop notification via
`notify-send` (Linux) and can ping a Discord/Slack webhook.

Alchemy principle: "As above, so below" — the same watcher spirit
guards your coin.
"""

import argparse
import json
import os
import sys
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import requests
import feedparser
from rich.console import Console
from rich.table import Table

console = Console()

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / "data"
CACHE_FILE = CACHE_DIR / "seen_studies.json"
CONFIG_FILE = CACHE_DIR / "config.json"

DEFAULT_SOURCES = {
    "reddit": {
        # One combined feed = one polite request instead of three.
        "url": "https://www.reddit.com/r/beermoney+WorkOnline+slavelabour/new/.rss?limit=30",
        "type": "rss",
    },
    "gnews": {
        # Google News RSS rarely throttles; catches paid-study news too.
        "url": "https://news.google.com/rss/search?q=paid+studies+OR+microtasks+OR+%22user+testing%22+OR+beermoney&hl=en-US&gl=US&ceid=US:en",
        "type": "rss",
    },
    # Prolific's feed now requires a logged-in session — uncomment if
    # it ever opens up again.
    # "prolific": {"url": "https://www.prolific.co/studies?format=rss", "type": "rss"},
}

DEFAULT_HOOK = {
    "enabled": False,
    "kind": "discord",          # or "slack" / "null"
    "webhook_url": "",
}


def ensure_dirs():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not CACHE_FILE.exists():
        save_cache({})
    if not CONFIG_FILE.exists():
        save_config({"min_payout": 0.0, "sources": DEFAULT_SOURCES, "hook": DEFAULT_HOOK})


def load_cache() -> dict:
    with open(CACHE_FILE) as f:
        return json.load(f)


def save_cache(cache: dict):
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- parsing
def parse_payout(text: str) -> float:
    """Pull a payout from a title like '$200 re-selling on Vinted' or '£0.60 study'.

    Only currency-marked amounts count ('$', '£', '€'); bare numbers like
    '2026' are years, not payouts. Values capped at $999 to filter noise.
    """
    import re

    match = re.search(r"(?:[$\u00a3\u20ac])\s?([\d,]+(?:\.\d{1,2})?)", text)
    if not match:
        return 0.0
    # Hype words in big-money headlines are not payouts.
    if re.search(r"\b(million|billion|trillion)\b", text, re.IGNORECASE):
        return 0.0
    try:
        val = float(match.group(1).replace(",", ""))
    except ValueError:
        return 0.0
    return val if val < 999 else 0.0


def fetch_rss(url: str, source_name: str, timeout: int = 20, retries: int = 3) -> list[dict]:
    console.print(f"  [dim]scanning RSS[/] {url}")
    for attempt in range(retries):
        try:
            resp = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0"},
            )
            if resp.status_code == 429:
                wait = 8 * (attempt + 1)
                console.print(f"  [yellow]rate-limited (429) — retrying in {wait}s ({attempt+1}/{retries})[/]")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        except requests.HTTPError as e:
            if attempt == retries - 1:
                console.print(f"  [yellow]RSS request failed: {e}[/]")
                return []
            time.sleep(4 * (attempt + 1))
    else:
        console.print("  [yellow]feed still throttled — skipping this round[/]")
        return []

    # Guard against sites that answer XML requests with an HTML login wall.
    if "text/html" in resp.headers.get("content-type", ""):
        console.print("  [yellow]source returned HTML (login wall?) — skipping[/]")
        return []

    f = feedparser.parse(resp.content)
    items = []
    for entry in f.entries:
        title = entry.get("title", "Untitled study")
        payout = parse_payout(title)
        items.append(
            {
                "title": title,
                "payout": payout,
                "link": entry.get("link", url),
                "published": entry.get("published", entry.get("updated", "")),
                "source": source_name,
            }
        )
    return items


def fetch_mturk(timeout: int = 20) -> list[dict]:
    """Best-effort scan of MTurk's public HIT listing page.

    MTurk's layout changes often; if this returns nothing, the
    aggregator simply skips it — your cache still runs clean.
    """
    console.print("  [dim]scanning mturk.com (best-effort)[/]")
    from bs4 import BeautifulSoup

    try:
        r = requests.get(
            "https://www.mturk.com/mturk/searchbar?selectedSearchType=hitgroups",
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
        )
        r.raise_for_status()
    except Exception as e:
        console.print(f"  [yellow]MTurk scan skipped: {e}[/]")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    items = []
    for tag in soup.select(".hit-group, article, .search-result"):
        title = tag.get_text(" ", strip=True)[:120]
        if title:
            items.append(
                {
                    "title": title,
                    "payout": parse_payout(title),
                    "link": "https://www.mturk.com",
                    "published": now_iso(),
                    "source": "mturk",
                }
            )
    return items


def collect(cfg: dict) -> list[dict]:
    all_items = []
    for name, src in cfg.get("sources", DEFAULT_SOURCES).items():
        kind = src.get("type", "rss")
        if kind == "rss":
            try:
                all_items.extend(fetch_rss(src["url"], name))
            except Exception as e:
                console.print(f"  [red]error on {name}: {e}[/]")
        elif name == "mturk":
            all_items.extend(fetch_mturk())
        time.sleep(2.0)  # politeness between feeds — avoids rate-limit 429s
    return all_items


# ---------------------------------------------------------------- reporting
def notify_desktop(title: str, body: str):
    try:
        import subprocess

        subprocess.run(
            ["notify-send", "--app-name=SeekersLens", title, body],
            check=False,
            timeout=5,
        )
    except Exception:
        pass


def notify_webhook(hook: dict, title: str, body: str):
    if not hook.get("enabled") or not hook.get("webhook_url"):
        return
    kind = hook.get("kind", "discord")
    if kind == "discord":
        payload = {"content": f"**{title}**\n{body}"}
    elif kind == "slack":
        payload = {"text": f"*{title}*\n{body}"}
    else:
        return
    try:
        requests.post(hook["webhook_url"], json=payload, timeout=10)
    except Exception as e:
        console.print(f"  [red]webhook failed: {e}[/]")


def render_table(new_items: list[dict]) -> None:
    table = Table(title="✦ New Opportunities ✦")
    table.add_column("Source", style="cyan")
    table.add_column("Payout", justify="right", style="green")
    table.add_column("Title / Link", style="white")
    for it in sorted(new_items, key=lambda x: x["payout"], reverse=True):
        table.add_row(
            it["source"].upper(),
            f"${it['payout']:.2f}",
            f"{it['title'][:70]}\n[link={it['link']}]{it['link']}[/link]",
        )
    console.print(table)


def run_scan(cfg: dict, threshold: float, open_browser: bool = False) -> int:
    cache = load_cache()
    seen = set(cache.keys())
    items = collect(cfg)
    now = now_iso()

    new_items = []
    for it in items:
        key = f"{it['source']}::{it['title']}"
        if key in seen:
            continue
        if it["payout"] < threshold:
            continue
        cache[key] = {"first_seen": now, "last_seen": now, **it}
        new_items.append(it)

    save_cache(cache)
    if not new_items:
        console.print("[dim]Nothing new under the sun... yet. ☽[/]")
        return 0

    render_table(new_items)
    total = sum(i["payout"] for i in new_items if i["payout"])
    console.print(f"[bold]Pooled value of new finds: ${total:.2f}[/]")

    # Alerts — desktop + webhook
    for it in new_items[:5]:
        notify_desktop(
            f"SeekersLens: {it['source'].upper()} {it['payout']:.2f}",
            it["title"][:80],
        )
    hook = cfg.get("hook", DEFAULT_HOOK)
    notify_webhook(hook, "New micro-tasks found", "\n".join(i["title"] for i in new_items[:5]))

    if open_browser:
        for it in new_items[:3]:
            webbrowser.open(it["link"])
    return len(new_items)


def show_history(limit: int = 20):
    cache = load_cache()
    if not cache:
        console.print("[dim]No history yet. Run a scan first.[/]")
        return
    table = Table(title="✦ Seen History ✦")
    table.add_column("First seen", style="cyan")
    table.add_column("Payout", justify="right", style="green")
    table.add_column("Title", style="white")
    by_time = sorted(cache.items(), key=lambda kv: kv[1]["first_seen"], reverse=True)
    for key, val in by_time[:limit]:
        table.add_row(val["first_seen"][:16], f"${val['payout']:.2f}", val["title"][:70])
    console.print(table)


def main():
    parser = argparse.ArgumentParser(description="Seeker's Lens — micro-task aggregator")
    parser.add_argument("--watch", type=float, default=0, help="rescan every N minutes")
    parser.add_argument("--threshold", type=float, default=0.0, help="min payout to report")
    parser.add_argument("--open", action="store_true", help="open top links in browser")
    parser.add_argument("--history", action="store_true", help="show previously found items")
    args = parser.parse_args()

    ensure_dirs()
    cfg = load_config()

    if args.history:
        show_history()
        return

    console.print("[bold]☿ SeekersLens spooling up...[/]")
    while True:
        found = run_scan(cfg, threshold=args.threshold, open_browser=args.open)
        if not args.watch:
            break
        console.print(f"[dim]sleeping {args.watch:.0f} min... ♄ patience (or automation)[/]")
        try:
            time.sleep(args.watch * 60)
        except KeyboardInterrupt:
            console.print("\n[bold]By the mercury of swift action — goodbye.[/]")
            break


if __name__ == "__main__":
    main()