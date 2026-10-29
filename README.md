# poly-predict

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

---

## 中文版

总在 Polymarket 上看到觉得「定价不对」的盘，就写了这个来验证：我的「不对」到底是真有差价，还是只是感觉。它给两类市场建模算公允概率，跟实时盘口比，把差价按一套纪律记成纸面信号。只有虚拟资金，从不下单、不持有密钥。纯标准库，一个主文件。

### 模型

币价类（BTC / ETH / SOL / XRP：每日 Above 盘、月度 Reach/Dip 盘）：零漂移 GBM，到期型用数字期权公式、首达型用障碍公式。波动率取 Binance 已实现波动率，短周期用小时级混合、长周期用日级。

天气类（14 个城市的每日最高/最低温分桶盘）：概率用 Open-Meteo 的 GFS 集合预报（31 个成员）数占比，再做一次校准收缩，下限 0.02、上限 0.90——集合计数在尾部容易过度自信，不缩不行。

体育和政治没接：没有我信得过的免费概率源，烂模型比没模型更坑。

### 纪律（这个项目真正的重点）

页面上显示的是中间价，而中间价是买不到的。扫描器会走真实 CLOB 订单簿，按目标金额算 VWAP。候选要成为正式信号，必须同时满足：

- 走完订单簿后的可执行差价 ≥ 8 pp
- 成本 ≤ 0.5，只买便宜边，不为「稳赢」付高价
- 订单簿价差 ≤ 0.05
- 所选边的模型胜率 ≥ 25 %，再便宜的彩票型也不做
- 仓位 = 四分之一凯利，单条 ≤ 净值 5 %、同资产同到期一组 ≤ 10 %，最小 $5

差一点的（差价 ≥ 5 pp、成本 ≤ 0.45、胜率 ≥ 30 %）进观察名单：照样跟踪结算，但不计正式战绩。到期按官方结果结算，累计统计有笔数、胜率、纸面盈亏、ROI 和 Brier 分数。

说个第一周的真事：早期版本成本闸门接错了，五笔天气单以 0.52–0.59 的成本记了账——而 0.5 上限正是这套策略的命根子。发现后我把闸门改对，那五笔单独计分，没混进正式战绩里。第一个完全合规过闸的信号是 ETH 月度「摸 $2,400」买 NO，成本约 0.44。

`promote_watchlist.py` 是个小工具：把达到正式门槛的观察名单条目晋升，并打印正式信号里成本超过 0.5 的报警清单（上面那个 bug 就是靠它发现的）。

### 跑法

```bash
cp config.example.json config.json   # 可选，没设的项用默认值
python3 predict.py                    # 跑一次：发现、打分、结算、记账
python3 predict.py daily              # 经 Telegram 发战绩汇总
```

我的 cron 是早晚各扫一次、下午发日报：

```cron
0 9,21 * * *  cd /opt/poly-predict && /usr/bin/python3 predict.py >> scan.log 2>&1
0 16 * * *    cd /opt/poly-predict && /usr/bin/python3 predict.py daily >> scan.log 2>&1
```

状态在 `state.json`，正式信号追加到 `ledger.jsonl`，观察名单到 `watch-ledger.jsonl`，都在脚本同目录。日报推送需要把 bot token 单独存文件、config 里填 chat ID；扫描本身只写本地文件。

配置键：`edge_min` 正式信号最低差价（0.08）、`cheap_max` 最高成本（0.5）、`min_winp` 最低胜率（0.25）、`watch_*` 三个观察名单闸门（0.05/0.45/0.30）、`max_spread` 最大盘口价差（0.05）、`bankroll` 虚拟本金（1000）、`kelly_fraction` 凯利倍数（0.25）、`max_single_fraction`/`max_group_fraction` 仓位上限（5%/10%）、`min_stake` 最小下注（$5）、`assets` 资产映射、`telegram.*` 日报推送。全集看示例文件。

纸面成绩必然比实盘好看：没有排队位置、没有部分成交、没有提现成本，盘还可能被暂停；模型平均而言是对的，照样输掉很多单笔。天气那边还依赖 Polymarket 不改市场命名、Open-Meteo 不改接口——两边都抽过风。研究工具，不是投资建议。报告文案是中文字符串。

MIT，见 LICENSE。
