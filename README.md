# poly-predict

English | [简体中文](README_zh.md)

I kept seeing Polymarket prices that looked wrong, so I built this to check whether my idea of "wrong" actually finds an edge or just feels like one. It models fair probabilities for two market families, compares them with the live book, and logs the gaps as paper signals. Virtual money only — it never places an order and holds no keys. Stdlib only, one main file.

## What it models

Crypto price markets (BTC / ETH / SOL / XRP: daily "above" markets, monthly "reach / dip" markets). Zero-drift GBM, with the terminal formula for digitals and the first-passage formula for barriers. Volatility is Binance realized vol — an hourly blend for short horizons, daily for longer ones.

Weather markets (daily high/low temperature buckets for 14 cities). Probabilities are counted from the Open-Meteo GFS ensemble (31 members), then shrunk a bit for calibration: floor 0.02, cap 0.90. Ensemble counts get overconfident at the tails, hence the shrink.

Sports and politics are not covered. I don't have a free probability source for them that I'd trust, and a bad model is worse than no model.

## The discipline (this is the actual point of the project)

The price on the market page is a mid, and you can't buy a mid. The scanner walks the real CLOB order book and computes the VWAP for the intended stake. A candidate becomes a formal signal only if all of these hold:

- executable edge ≥ 8 pp after walking the book
- cost ≤ 0.5 — cheap side only, no paying up for "sure things"
- order-book spread ≤ 0.05
- model win probability of the chosen side ≥ 25 % — no lottery tickets, however cheap they look
- stake = quarter-Kelly, capped at 5 % of equity per signal and 10 % per asset/expiry group, minimum $5

Near-misses (edge ≥ 5 pp, cost ≤ 0.45, win probability ≥ 30 %) go to a watchlist instead: tracked and settled, but kept out of the formal record. After expiry, signals settle against the official outcome; running stats are count, win rate, paper P&L, ROI and Brier score.

An honest bug from the first week: an early version had the cost gate mis-wired, and five weather positions got logged at costs of 0.52–0.59 — above the 0.5 cap that's the whole point of the strategy. I fixed the gate and scored those five separately instead of quietly folding them into the record. The first signal that passed every gate properly was an ETH monthly "reach $2,400" NO at about 0.44.

`promote_watchlist.py` is a small helper: it promotes watchlist entries that now meet the formal bar, and prints any formal signals whose cost exceeded 0.5 (which is how the bug above got caught).

## Running it

```bash
cp config.example.json config.json   # optional; anything unset uses the defaults
python3 predict.py                    # one scan: discover, score, settle, log
python3 predict.py daily              # Telegram summary of the running record
```

My cron looks like:

```cron
0 9,21 * * *  cd /opt/poly-predict && /usr/bin/python3 predict.py >> scan.log 2>&1
0 16 * * *    cd /opt/poly-predict && /usr/bin/python3 predict.py daily >> scan.log 2>&1
```

State is `state.json`; formal signals append to `ledger.jsonl`, watchlist entries to `watch-ledger.jsonl`, all next to the script. The Telegram summary needs a bot token in its own file plus a chat ID in config; the scans themselves only write local files.

## Config

| Key | What it does |
| --- | --- |
| `edge_min` | Min executable edge for a formal signal (0.08) |
| `cheap_max` | Max execution cost for a formal signal (0.5) |
| `min_winp` | Min model win probability of the chosen side (0.25) |
| `watch_edge_min` / `watch_cheap_max` / `watch_min_winp` | Watchlist gates (0.05 / 0.45 / 0.30) |
| `max_spread` | Max allowed book spread (0.05) |
| `bankroll` | Virtual bankroll (1000) |
| `kelly_fraction` | Kelly multiplier (0.25) |
| `max_single_fraction` / `max_group_fraction` | Equity caps per signal / per group (5 % / 10 %) |
| `min_stake` | Minimum formal stake ($5) |
| `assets` | Polymarket asset name → Binance symbol map |
| `telegram.*` | Optional daily summary push |

Paper results flatter reality: no queue position, no partial fills, no withdrawal costs, and markets can be suspended. A model that's right on average still loses plenty of individual bets. The weather side also depends on Polymarket keeping its market naming conventions and Open-Meteo keeping its API — both have broken before. Research tool, not financial advice. Report texts are Chinese literals.

MIT license, see LICENSE.
