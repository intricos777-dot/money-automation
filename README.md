<!-- Watermark: Living_Sin (intricos777-dot) + AI agents (Hermes, Lia, opencode) - collaborative work -->
# Money Automation — The Forge ⚗️

Three small engines that help you find and produce ways to earn online,
built for a weekly "small money" side income.

> *"As above, so below."* — every tool here is a lens on the same
> principle: **consistent small actions, compounded.**

---

## Setup

```bash
cd money-automation
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

---

## 1. Seeker's Lens ☿ — micro-task & opportunity aggregator

Watches public feeds (r/beermoney, r/WorkOnline, r/slavelabour combined
feed + Google News) and reports **new** paid studies, gig offers, and
micro-task opportunities. Tracks everything it has already seen so you
only get fresh finds.

```bash
.venv/bin/python aggregator.py                       # one-shot scan
.venv/bin/python aggregator.py --watch 5             # rescan every 5 min
.venv/bin/python aggregator.py --threshold 1         # only postings ≥ $1
.venv/bin/python aggregator.py --open                # open new finds in browser
.venv/bin/python aggregator.py --history             # previously found items
```

Notifications: desktop via `notify-send` (Linux), optionally Discord or
Slack — edit `data/config.json` → `hook`.

> The Prolific feed itself now requires a login, so the lens relies on
> the community feeds where opportunities are shared daily.

## 2. Quill of Mercury 🜁 — content generator

Produces SEO blog articles, product descriptions, and social captions
you can refine and sell or post.

```bash
.venv/bin/python content_gen.py "budget keyboards" --length 600
.venv/bin/python content_gen.py "cotton tote" --mode product --price 24.99
.venv/bin/python content_gen.py "moon journaling" --mode caption --platform instagram
.venv/bin/python content_gen.py "topic" --variations 5 --seed 42
```

Output lands in `output/` as Markdown. **Edit before publishing** —
the drafts are skeletons; your voice is the flesh.

## 3. Dowsing Rod 🜃 — reselling deal finder

Finds underpriced listings and flags them when your implied margin beats
a target.

```bash
# Craigslist (no key needed)
.venv/bin/python dealfinder.py craigslist --query "trek mountain bike" \
    --area minneapolis --resale 350 --target 50

# eBay (free official API key — the reliable path)
.venv/bin/python dealfinder.py ebay --query "lego star wars sealed" \
    --api-key YOUR_EBAY_KEY --resale 120 --target 40

# Watch mode
.venv/bin/python dealfinder.py watch --query "camera lens" \
    --api-key YOUR_EBAY_KEY --interval 15
```

Get your free eBay key at https://developer.ebay.com (use a *production*
app). Fee model: eBay ~13% + ~6% shipping, built into margin math.

---

## Automating a weekly routine — cron

Run the aggregator daily and the content quill on a schedule:

```cron
# every day at 8am — scan for opportunities
0 8 * * * cd /home/sin/money-automation && .venv/bin/python aggregator.py >/dev/null 2>&1

# every Monday — generate 5 product drafts for the week
0 9 * * 1 cd /home/sin/money-automation && .venv/bin/python content_gen.py "your niche" --mode product --variations 5 >/dev/null 2>&1
```

## House rules ♄

- **Verify before you invest:** check *sold* prices, not listed prices;
  factor fees/shipping; never trust "too good" listings.
- **Never pay to earn.** Legit platforms don't charge you to apply.
- **Rate limits are real:** the scripts use polite delays and retries.
  Don't shrink the intervals.
- **The tools assist; you are the artisan.** Rough edges of drafts,
  scams, and negotiations always need human eyes.

> *"The philosopher's stone is forged one step at a time."*