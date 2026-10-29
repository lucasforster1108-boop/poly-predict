#!/usr/bin/env python3
"""promote_watchlist.py - one-off maintenance helper for poly-predict.

Run it from the poly-predict directory (it reads/writes state.json,
watch-ledger.jsonl and ledger.jsonl in the current directory):
- promotes watchlist entries that meet the formal-signal bar
  (edge >= 8pp, cost <= 0.5, model win probability >= 25%) into the
  "signaled" set in state.json, staking them with quarter-Kelly against
  a 1000 bankroll (matching BANKROLL's default in predict.py);
- prints an alert list of already-signaled entries whose cost exceeded 0.5.
"""

import json

# 读取 state.json
with open('state.json', 'r') as f:
    state = json.load(f)

# 读取 watch-ledger.jsonl
watchlist = {}
with open('watch-ledger.jsonl', 'r') as f:
    for line in f:
        entry = json.loads(line.strip())
        watchlist[entry['id']] = entry

# 筛选符合晋升条件的观察名单：diff ≥8pp, cost ≤0.5, winp ≥25%
promoted = []
for id_, entry in watchlist.items():
    model = entry.get('model', 0)
    market = entry.get('market', 0)
    cost = entry.get('cost', 1)
    winp = entry.get('winp', 0)
    diff = abs(model - market) * 100  # pp
    
    if diff >= 8 and cost <= 0.5 and winp >= 0.25:
        promoted.append((id_, entry, diff))

print(f"符合晋升条件: {len(promoted)} 条")
for id_, entry, diff in promoted:
    print(f"  {id_}: {entry['q'][:50]}... diff={diff:.2f}pp cost={entry['cost']:.4f} winp={entry['winp']:.4f}")

# 检查已有正式信号中 cost > 0.5 的
alerts = []
for id_, entry in state.get('signaled', {}).items():
    cost = entry.get('cost', 0)
    if cost > 0.5:
        alerts.append((id_, entry['q'][:50], cost))

print(f"\n正式信号 cost>0.5 报警: {len(alerts)} 条")
for id_, q, cost in alerts:
    print(f"  {id_}: {q}... cost={cost:.4f}")

# 执行晋升
for id_, entry, diff in promoted:
    payout = entry.get('payout', 1)
    winp = entry.get('winp', 0)
    edge = entry.get('edge', 0)
    if payout > 1:
        kelly = edge / (payout - 1) if edge > 0 else 0
    else:
        kelly = 0
    quarter_kelly = max(kelly / 4, 0)
    stake = round(1000 * quarter_kelly, 2)
    shares = round(stake / entry['cost'], 2) if entry['cost'] > 0 else 0
    
    entry['stake'] = stake
    entry['shares'] = shares
    
    state['signaled'][id_] = entry
    del watchlist[id_]
    
    with open('ledger.jsonl', 'a') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    print(f"晋升: {id_} stake=${stake} shares={shares} quarter_kelly={quarter_kelly:.4f}")

# 重写 state.json
with open('state.json', 'w') as f:
    json.dump(state, f, ensure_ascii=False)

# 重写 watch-ledger.jsonl
with open('watch-ledger.jsonl', 'w') as f:
    for entry in watchlist.values():
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

print(f"\n完成。剩余观察名单: {len(watchlist)} 条")