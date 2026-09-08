#!/usr/bin/env python3
"""
The Dowsing Rod — Reselling Deal Finder
=======================================
Scans marketplaces for underpriced listings so you can flip them.

Two proven engines:

  1. CRAIGSLIST (no key, works today)
     Uses the site's public embedded result data (JSON-LD).
     Reports live listings with title, price, and location.

  2. EBAY — Browse API (free developer key, the reliable path)
     eBay blocks plain scraping (HTTP 403). Their official Browse API
     is free to use: create a key at https://developer.ebay.com
     (Developer -> "Get a token"/Create an app -> prod keys).
     Pass it with --api-key. National listings with real links.

Arbitrage math used for flags:

    net  = (resale_value × 1.02) − price − fees − shipping
    margin% = net / price × 100

Usage:
  python3 dealfinder.py craigslist --query "mountain bike" --area minneapolis --resale 300
  python3 dealfinder.py ebay --query "lego star wars sealed" --api-key YOUR_KEY --resale 120 --target 40
  python3 dealfinder.py watch --source ebay --query "camera lens" --api-key YOUR_KEY --interval 15

Alchemy rule: verify *sold* prices before assuming a resale value,
and factor platform fees (~13% eBay) + shipping into your margin.

Alchemy principle: "Solve et coagula" — dissolve clutter, coagulate margin.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests
from rich.console import Console
from rich.table import Table

console = Console()

BASE_DIR = Path(__file__).parent
CACHE_FILE = BASE_DIR / "data" / "dealfinder_cache.html"
CACHE_FILE.parent.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Accept-Language": "en-US,en;q=0.9",
}

# Modeled fees per platform (fraction of purchase price)
FEES = {"ebay": 0.132, "craigslist": 0.0}


# ------------------------------------------------------------ craigslist
def _fetch(url: str, timeout: int = 25) -> str:
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    CACHE_FILE.write_text(r.text)
    return r.text


def scrape_craigslist(query: str, area: str, max_items: int = 40) -> list[dict]:
    """Parse Craiglist's public JSON-LD result data (no login, no JS)."""
    console.print(f"  [dim]craigslist.org/{area} :: '{query}'[/]")
    url = f"https://{area}.craigslist.org/search/sss?query={requests.utils.quote(query)}"
    text = _fetch(url)
    blocks = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', text, re.S)
    items = []
    for block in blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        elems = data.get("itemListElement") or []
        for entry in elems:
            item = entry.get("item", {})
            offers = item.get("offers", {})
            price_raw = offers.get("price")
            if not price_raw:
                continue
            try:
                price = float(price_raw)
            except (TypeError, ValueError):
                continue
            loc = ""
            place = offers.get("availableAtOrFrom", {})
            addr = place.get("address", {}) if isinstance(place, dict) else {}
            loc = f"{addr.get('addressLocality', '')}, {addr.get('addressRegion', '')}".strip(", ")
            items.append(
                {
                    "source": "craigslist",
                    "title": item.get("name", "untitled"),
                    "price": price,
                    "location": loc,
                    "image": (item.get("image") or [""])[0],
                    "link": f"https://{area}.craigslist.org/search/sss?query={requests.utils.quote(item.get('name', query))}",
                }
            )
            if len(items) >= max_items:
                return items
    if not items:
        console.print("  [yellow]no listings parsed (site changed?) — check manually[/]")
    return items


# --------------------------------------------------------------- ebay API
def scrape_ebay_api(query: str, api_key: str, max_items: int = 25) -> list[dict]:
    """Official eBay Browse API: https://developer.ebay.com (free key)."""
    console.print("  [dim]ebay Browse API :: searching[/]")
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Accept": "application/json",
    }
    params = {"q": query, "limit": str(max_items)}  # sort defaults to "Best Match"
    r = requests.get(url, headers=headers, params=params, timeout=30)
    if r.status_code in (401, 403):
        raise PermissionError(
            "eBay rejected the key (401/403). Double-check the key was "
            "generated in the PRODUCTION section, not the sandbox."
        )
    r.raise_for_status()
    data = r.json()
    items = []
    for s in data.get("itemSummaries", []):
        price_block = (s.get("price") or {})
        try:
            price = float(price_block.get("value", 0))
        except (TypeError, ValueError):
            price = 0.0
        if not price:
            continue
        items.append(
            {
                "source": "ebay",
                "title": s.get("title", "untitled"),
                "price": price,
                "location": "",
                "image": (s.get("image") or {}).get("imageUrl", ""),
                "link": s.get("itemWebUrl", f"https://www.ebay.com/sch/i.html?_nkw={requests.utils.quote(query)}"),
                "condition": (s.get("condition") or ""),
                "sold_metrics": "",
            }
        )
    return items


def scrape_ebay_html(query: str, max_items: int = 25) -> list[dict]:
    """Plain-sited fallback; often 403 — the API is the honest path."""
    console.print("  [dim]ebay html scrape (best-effort)[/]")
    url = f"https://www.ebay.com/sch/i.html?_nkw={requests.utils.quote(query)}&_sacat=0"
    text = _fetch(url)
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(text, "html.parser")
    items = []
    for container in soup.select("li.s-item"):
        title_el = container.select_one(".s-item__title")
        price_el = container.select_one(".s-item__price")
        link_el = container.select_one("a.s-item__link")
        if not title_el or not price_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if title.lower() == "shop on ebay":
            continue
        m = re.search(r"\$\s?([\d,]+(?:\.\d{1,2})?)", price_el.get_text(" ", strip=True))
        if not m:
            continue
        items.append(
            {
                "source": "ebay",
                "title": title,
                "price": float(m.group(1).replace(",", "")),
                "location": "",
                "image": "",
                "link": link_el["href"] if link_el else url,
            }
        )
        if len(items) >= max_items:
            break
    return items


# ---------------------------------------------------------------- eval
def margin(purchase: float, resale: float, source: str) -> float:
    fee = purchase * FEES.get(source, 0.1)
    shipping = purchase * 0.06
    net = resale * 1.02 - purchase - fee - shipping
    return (net / purchase * 100) if purchase else 0.0


def report(items: list[dict], target: float) -> None:
    table = Table(title="✦ Deal Finds ✦", title_style="bold green")
    table.add_column("Source", style="cyan")
    table.add_column("Market", justify="right", style="yellow")
    table.add_column("Title", style="white")
    table.add_column("Margin", justify="right", style="green")
    flagged = 0
    for it in items:
        pct = margin(it["price"], args.resale or it["price"] * 1.5, it["source"])
        if pct >= target:
            flagged += 1
        flag = " ← flip" if pct >= target else ""
        table.add_row(
            it["source"].upper(),
            f"${it['price']:.2f}",
            f"{it['title'][:58]}" + (f" @{it['location']}" if it.get("location") else ""),
            f"{pct:.0f}%{flag}",
        )
    console.print(table)
    console.print(f"[bold]Flags: {flagged}/{len(items)} at ≥ {target:.0f}% margin[/]"
                  f" — assumes resale ≈ ${args.resale or '1.5×'}.")
    console.print("[dim]Open the listing link and eyeball condition/shipping before buying.[/]")


def run(source: str, query: str, api_key: str, resale: float | None, target: float, area: str) -> list[dict]:
    if source == "craigslist":
        return scrape_craigslist(query, area)
    if source == "ebay":
        if api_key:
            return scrape_ebay_api(query, api_key)
        try:
            return scrape_ebay_html(query)
        except requests.HTTPError as e:
            if e.response.status_code == 403:
                console.print(
                    "\n[red]eBay blocks plain scraping (403).[/]\n"
                    "The proper path is their free Browse API:\n"
                    "  1. Create a (free) developer account at https://developer.ebay.com\n"
                    "  2. App → create a 'production' key\n"
                    "  3. Pass it:  --api-key YOUR_KEY\n"
                )
                sys.exit(1)
            raise
    raise ValueError(f"unknown source {source}")


def main():
    global args
    parser = argparse.ArgumentParser(description="Dowsing Rod — deal finder",
                                     epilog="Tip: verify sold prices, not active ones.")
    parser.add_argument("source", choices=["craigslist", "ebay", "watch"])
    parser.add_argument("--query", required=True, help="search term, e.g. 'vintage watch'")
    parser.add_argument("--area", default="minneapolis", help="craigslist area subdomain (default minneapolis)")
    parser.add_argument("--resale", type=float, default=None, help="your expected resale value")
    parser.add_argument("--target", type=float, default=30, help="min margin (percent) to flag")
    parser.add_argument("--api-key", default="", help="eBay Browse API production key")
    parser.add_argument("--interval", type=float, default=15, help="minutes between scans (watch mode)")
    args = parser.parse_args()

    if args.source == "watch":
        src = args.query  # watch uses query as source? no — watch on CURRENT defaults
        console.print("[bold]☿ Dowsing Rod in watch mode — I will be back every few minutes.[/]")
        while True:
            try:
                items = run("ebay" if args.api_key else "craigslist", args.query, args.api_key, args.resale, args.target, args.area)
                report(items, args.target)
            except KeyboardInterrupt:
                console.print("\n[bold]The rod rests. Good hunting.[/]")
                break
            except Exception as e:
                console.print(f"  [red]scan error (retrying): {e}[/]")
            try:
                time.sleep(args.interval * 60)
            except KeyboardInterrupt:
                console.print("\n[bold]The rod rests. Good hunting.[/]")
                break
    else:
        items = run(args.source, args.query, args.api_key, args.resale, args.target, args.area)
        report(items, args.target)


if __name__ == "__main__":
    main()