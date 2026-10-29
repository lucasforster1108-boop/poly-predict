# poly-predict

A **paper-tracking** signal scanner for Polymarket: **pure Python standard library, single file, virtual money only — it never places orders and holds no keys.** It models fair probabilities for two market families, compares them with live prices, and logs the gaps as paper signals with disciplined, cheap-side-only rules.

## What it models

**Crypto price markets** (BTC / ETH / SOL / XRP: daily "above" markets and monthly "reach/dip" markets)
- Zero-drift GBM probabilities: terminal (digital) and first-passage (barrier) formulas
- Volatility from Binance realized vol — hourly blend for short horizons, daily for longer ones

**Weather markets** (daily highest/lowest temperature buckets for 14 cities)
- Probabilities counted from the Open-Meteo GFS ensemble (31 members), with a calibration shrink applied (floor 0.02 / cap 0.90)

## Signal discipline

Execution prices are **not** the displayed mid: the scanner walks the real CLOB order book and uses the VWAP for the intended stake. A candidate becomes a formal paper signal only when all gates pass:

- executable edge ≥ 8 pp after the order book
- cost within the configured cap, and order-book spread ≤ 0.05
- model win probability of the chosen side ≥ 25 % (no lottery tickets, however cheap)
- stake = quarter-Kelly, capped at 5 % of equity per signal and 10 % per asset/expiry group, minimum $5

Near-misses (edge ≥ 5 pp, cost ≤ 0.45, win probability ≥ 30 %) go to a **watchlist** instead — tracked, but excluded from the formal track record. Settlements are resolved against the official market outcome after expiry; running stats include count, win rate, paper P&L, ROI and Brier score. A daily summary can be pushed to Telegram (`daily` command); scans themselves only log locally.

`promote_watchlist.py` is a small maintenance helper: it promotes watchlist entries that meet the formal bar into the signaled set, and prints an alert list of signaled entries whose cost exceeded 0.5.

## Deployment

1. **Configure (optional)**: `cp config.example.json config.json`. Defaults (in the example file) are used for anything unset. For the Telegram daily report, store your bot token in its own file and set `telegram.bot_token_file` + `telegram.chat_id`.
2. **Run**:

   ```bash
   python3 predict.py          # one scan: discover, score, settle, log
   python3 predict.py daily    # send the daily P&L summary via Telegram
   ```

   Typical cron setup:

   ```cron
   0 9,21 * * *  cd /opt/poly-predict && /usr/bin/python3 predict.py >> scan.log 2>&1
   0 16 * * *    cd /opt/poly-predict && /usr/bin/python3 predict.py daily >> scan.log 2>&1
   ```

State lives in `state.json`; formal signals are appended to `ledger.jsonl`, watchlist entries to `watch-ledger.jsonl` — all next to the script.

## Configuration (config.json)

| Key | Description |
| --- | --- |
| `telegram.bot_token_file` / `telegram.chat_id` | Token file path and target chat for the daily report. Empty = no push. The token never goes into config or code. |
| `edge_min` | Minimum executable edge for a formal signal (default 0.08 = 8 pp). |
| `cheap_max` | Maximum execution cost for a formal signal. |
| `min_winp` | Minimum model win probability of the chosen side (default 0.25). |
| `watch_edge_min` / `watch_cheap_max` / `watch_min_winp` | Watchlist gates (defaults 0.05 / 0.45 / 0.30). |
| `max_spread` | Maximum allowed order-book spread (default 0.05). |
| `bankroll` | Virtual bankroll (default $1,000). |
| `kelly_fraction` | Kelly multiplier for staking (default 0.25 = quarter-Kelly). |
| `max_single_fraction` / `max_group_fraction` | Equity caps per signal / per asset+expiry group (defaults 5 % / 10 %). |
| `min_stake` | Minimum stake for a formal signal (default $5). |
| `assets` | Map of Polymarket asset names → Binance symbols for the crypto model. |

## Notes & disclaimer

- This is a **research/validation tool**, not financial advice. Prediction-market paper results ignore real-world frictions (queue position, partial fills, withdrawal costs, market suspensions) and a model being "right" on average still loses plenty of individual bets.
- The weather model depends on Open-Meteo's ensemble API and on Polymarket's market naming conventions; the crypto model depends on the public Gamma/CLOB APIs and Binance spot data. Any of these can change without notice.
- Report texts are in Chinese; they are plain string literals and can be replaced freely.

## Custom development

Thresholds, asset lists, cities and models are all adjustable. If you need a variant (other market families, alert channels, reporting), a customized or hosted version can be arranged — contact the author.

## License

MIT, see [LICENSE](LICENSE).

---

## 中文版

一个 Polymarket **纸面信号**扫描器：**纯 Python 标准库、单文件、只有虚拟资金——从不下单、不持有任何密钥。**它给两类市场建模算「公允概率」，与实时价格对比，把差价按严格的「只买便宜边」纪律记成纸面信号。

### 模型覆盖

**币价类市场**（BTC / ETH / SOL / XRP：每日 Above 盘、月度 Reach/Dip 盘）
- 零漂移 GBM 概率：到期型（数字期权式）与首达型（障碍式）两个公式
- 波动率取 Binance 已实现波动率——短周期用小时级混合、长周期用日级

**天气类市场**（14 个城市每日最高/最低温分桶盘）
- 概率用 Open-Meteo 的 GFS 集合预报（31 个成员）数成员占比，再做校准收缩（下限 0.02 / 上限 0.90）

### 信号纪律

执行价**不是**页面显示的中间价：扫描器会走真实 CLOB 订单簿，按目标金额算 VWAP。候选要成为正式纸面信号，必须同时过闸：

- 走完订单簿后的可执行差价 ≥ 8 pp
- 成本在配置上限内，且订单簿价差 ≤ 0.05
- 所选边的模型胜率 ≥ 25 %（再便宜的彩票型也不做）
- 仓位 = 四分之一凯利，单条 ≤ 净值 5 %、同资产同到期一组 ≤ 10 %，最小 $5

差一点的（差价 ≥ 5 pp、成本 ≤ 0.45、胜率 ≥ 30 %）进**观察名单**——只跟踪、不计正式战绩。到期后按官方结果结算；累计统计含笔数、胜率、纸面盈亏、ROI 和 Brier 分数。每日汇总可经 Telegram 推送（`daily` 命令）；扫描本身只写本地日志。

`promote_watchlist.py` 是个小维护工具：把达到正式门槛的观察名单条目晋升进正式信号集，并打印已正式信号中成本超过 0.5 的报警清单。

### 部署三步

1. **填配置（可选）**：`cp config.example.json config.json`，没设的项用示例文件里的默认值。想推 Telegram 日报：把 bot token 单独存一个文件，填 `telegram.bot_token_file` 和 `telegram.chat_id`。
2. **运行**：

   ```bash
   python3 predict.py          # 跑一次扫描：发现、打分、结算、记账
   python3 predict.py daily    # 经 Telegram 发每日盈亏汇总
   ```

   典型 cron：

   ```cron
   0 9,21 * * *  cd /opt/poly-predict && /usr/bin/python3 predict.py >> scan.log 2>&1
   0 16 * * *    cd /opt/poly-predict && /usr/bin/python3 predict.py daily >> scan.log 2>&1
   ```

状态在 `state.json`；正式信号追加到 `ledger.jsonl`，观察名单追加到 `watch-ledger.jsonl`，都在脚本同目录。

### 配置项说明（config.json）

| 键 | 说明 |
| --- | --- |
| `telegram.bot_token_file` / `telegram.chat_id` | 日报用的 token 文件路径和目标 chat。留空 = 不推送。token 不写进 config、更不写进代码。 |
| `edge_min` | 正式信号的最低可执行差价（默认 0.08 = 8 pp）。 |
| `cheap_max` | 正式信号的最高执行成本。 |
| `min_winp` | 所选边的最低模型胜率（默认 0.25）。 |
| `watch_edge_min` / `watch_cheap_max` / `watch_min_winp` | 观察名单闸门（默认 0.05 / 0.45 / 0.30）。 |
| `max_spread` | 允许的最大订单簿价差（默认 0.05）。 |
| `bankroll` | 虚拟本金（默认 $1,000）。 |
| `kelly_fraction` | 定仓的凯利倍数（默认 0.25 = 四分之一凯利）。 |
| `max_single_fraction` / `max_group_fraction` | 单条 / 同组仓位占净值上限（默认 5 % / 10 %）。 |
| `min_stake` | 正式信号的最小下注额（默认 $5）。 |
| `assets` | Polymarket 资产名 → Binance 币种符号的映射（币价模型用）。 |

### 说明与免责

- 这是**研究/验证工具**，不是投资建议。预测市场的纸面成绩忽略了真实摩擦（排队位置、部分成交、提现成本、市场暂停），而且模型「平均而言是对的」也照样会输掉很多单笔。
- 天气模型依赖 Open-Meteo 集合预报接口和 Polymarket 的市场命名规则；币价模型依赖公开的 Gamma/CLOB 接口和 Binance 现货数据。任何一方都可能随时变更。
- 报告文案为中文，都是普通字符串，可自行替换。

### 定制开发

阈值、资产表、城市表、模型都能自己改。如果需要变体（其他市场类别、告警通道、报表），需要定制版或代部署，可联系作者获取付费定制服务。

### License

MIT，见 [LICENSE](LICENSE)。
