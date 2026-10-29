#!/usr/bin/env python3
"""poly-predict v1: Polymarket crypto price markets — GBM model probability vs market price.
Paper-tracking only. Finds mispricings, logs signals, settles them after expiry, reports via TG.
Stdlib only. Model: zero-drift GBM; terminal digitals + first-passage (barrier) probabilities.
Volatility: Binance realized vol (hourly blend for short horizons, daily for longer)."""
import json, math, os, re, sys, time, urllib.request, urllib.parse, logging
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(BASE, 'ledger.jsonl')
WATCH_LEDGER = os.path.join(BASE, 'watch-ledger.jsonl')
STATEF = os.path.join(BASE, 'state.json')
DEFAULT_CONFIG = {
    'telegram': {'bot_token_file': '', 'chat_id': ''},
    'edge_min': 0.08,
    'cheap_max': 2.0,
    'min_winp': 0.25,
    'watch_edge_min': 0.05,
    'watch_cheap_max': 0.45,
    'watch_min_winp': 0.30,
    'max_spread': 0.05,
    'bankroll': 1000.0,
    'kelly_fraction': 0.25,
    'max_single_fraction': 0.05,
    'max_group_fraction': 0.10,
    'min_stake': 5.0,
    'assets': {'bitcoin': 'BTCUSDT', 'ethereum': 'ETHUSDT',
               'solana': 'SOLUSDT', 'xrp': 'XRPUSDT'},
}

def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    path = os.path.join(BASE, 'config.json')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            user = json.load(f)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg

CFG = load_config()
TG_CHAT = str((CFG.get('telegram') or {}).get('chat_id') or '')
EDGE_MIN = float(CFG['edge_min'])
CHEAP_MAX = float(CFG['cheap_max'])  # max execution cost for formal signals
MIN_WINP = float(CFG['min_winp'])  # skip if model win probability of the chosen side < 25%, however cheap
WATCH_EDGE_MIN = float(CFG['watch_edge_min'])
WATCH_CHEAP_MAX = float(CFG['watch_cheap_max'])
WATCH_MIN_WINP = float(CFG['watch_min_winp'])
MAX_SPREAD = float(CFG['max_spread'])
BANKROLL = float(CFG['bankroll'])
KELLY_FRACTION = float(CFG['kelly_fraction'])
MAX_SINGLE_FRACTION = float(CFG['max_single_fraction'])
MAX_GROUP_FRACTION = float(CFG['max_group_fraction'])
MIN_STAKE = float(CFG['min_stake'])
CLOB_BASE = 'https://clob.polymarket.com'
YEAR = 365.25 * 24 * 3600
ASSETS = dict(CFG['assets'])

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def ncdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def load_state():
    if os.path.exists(STATEF):
        st = json.load(open(STATEF))
    else:
        st = {}
    st.setdefault('signaled', {})
    st.setdefault('settled', {})
    st.setdefault('watchlist', {})
    stats = st.setdefault('stats', {})
    for k, v in {'n': 0, 'wins': 0, 'brier': 0.0, 'pnl': 0.0, 'staked': 0.0}.items():
        stats.setdefault(k, v)
    return st

def save_state(st):
    json.dump(st, open(STATEF, 'w'), indent=1)

def tg(text):
    try:
        tok = None
        tok_file = (CFG.get('telegram') or {}).get('bot_token_file') or ''
        if tok_file and os.path.exists(tok_file):
            tok = open(tok_file).read().strip()
        if not tok or not TG_CHAT:
            return
        
        # Split long messages (>4096 chars) into chunks
        max_len = 4096
        if len(text) <= max_len:
            _send_single(text, tok)
        else:
            # Split by lines first, then by chunks
            lines = text.split('\n')
            chunk = ''
            for line in lines:
                if len(chunk) + len(line) + 1 > max_len:
                    if chunk:
                        _send_single(chunk, tok)
                        chunk = ''
                chunk += line + '\n'
            if chunk:
                _send_single(chunk, tok)
    except Exception as e:
        print('tg failed:', e)

def _send_single(text, tok):
    data = urllib.parse.urlencode({'chat_id': TG_CHAT, 'text': text}).encode()
    req = urllib.request.Request(f'https://api.telegram.org/bot{tok}/sendMessage', data=data)
    urllib.request.urlopen(req, timeout=20).read()

def daily_report():
    """Send daily P&L report via Telegram"""
    st = load_state()
    stats = st.get('stats', {})
    
    if stats.get('n', 0) == 0:
        msg = "📊 Polymarket 每日盈亏报告\n\n暂无已结算信号"
    else:
        pnl = stats.get('pnl', 0.0)
        staked = stats.get('staked', 0.0)
        n = stats.get('n', 0)
        wins = stats.get('wins', 0)
        brier = stats.get('brier', 0.0)
        roi = (pnl / staked * 100) if staked > 0 else 0
        winrate = (wins / n * 100) if n > 0 else 0
        
        msg = (
            f"📊 Polymarket 每日盈亏报告\n\n"
            f"📈 累计信号: {n} 笔\n"
            f"✅ 命中: {wins} 笔 ({winrate:.1f}%)\n"
            f"💰 纸面盈亏: {pnl:+.2f} USDT\n"
            f"💵 总投入: {staked:.2f} USDT\n"
            f"📊 ROI: {roi:+.1f}%\n"
            f"📉 Brier Score: {brier/max(n,1):.4f}\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%m-%d %H:%M')} UTC"
        )
    
    tg(msg)
    print(f"Daily report sent: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")

_cache = {}
def spot_vol(sym):
    if sym in _cache:
        return _cache[sym]
    px = float(http_get(f'https://api.binance.com/api/v3/ticker/price?symbol={sym}')['price'])
    kl = http_get(f'https://api.binance.com/api/v3/klines?symbol={sym}&interval=1d&limit=91')
    closes = [float(k[4]) for k in kl]
    rd = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    def ann(rs, per_year):
        n = len(rs); m = sum(rs) / n
        return math.sqrt(sum((r - m) ** 2 for r in rs) / (n - 1)) * math.sqrt(per_year)
    sig_d = ann(rd[-60:], 365)
    kh = http_get(f'https://api.binance.com/api/v3/klines?symbol={sym}&interval=1h&limit=169')
    ch = [float(k[4]) for k in kh]
    rh = [math.log(ch[i] / ch[i - 1]) for i in range(1, len(ch))]
    sig_h = ann(rh, 8760)
    _cache[sym] = (px, sig_d, sig_h)
    return _cache[sym]

def p_terminal(S, K, T, sig, above):
    if T <= 0:
        return 1.0 if (S > K) == above else 0.0
    d2 = (math.log(S / K) - 0.5 * sig * sig * T) / (sig * math.sqrt(T))
    p = ncdf(d2)
    return p if above else 1.0 - p

def p_passage(S, K, T, sig, up):
    nu = -0.5 * sig * sig
    b = math.log(K / S)
    if up and b <= 0:
        return 1.0
    if not up and b >= 0:
        return 1.0
    if T <= 0:
        return 0.0
    sT = sig * math.sqrt(T)
    if up:
        return ncdf((nu * T - b) / sT) + math.exp(2 * nu * b / (sig * sig)) * ncdf((-nu * T - b) / sT)
    bb = -b; nn = -nu
    return ncdf((nn * T - bb) / sT) + math.exp(2 * nn * bb / (sig * sig)) * ncdf((-nn * T - bb) / sT)

def orderbook_quote(token_id, stake):
    try:
        b = http_get(f'{CLOB_BASE}/book?token_id={token_id}')
    except Exception:
        return None
    asks = sorted([(float(x['price']), float(x['size'])) for x in b.get('asks', [])])
    bids = sorted([(float(x['price']), float(x['size'])) for x in b.get('bids', [])], reverse=True)
    if not asks:
        return None
    best_ask = asks[0][0]
    best_bid = bids[0][0] if bids else 0.0
    remaining = float(stake); shares = 0.0; spent = 0.0
    for price, size in asks:
        if remaining <= 1e-9:
            break
        take_cost = min(remaining, price * size)
        shares += take_cost / price; spent += take_cost; remaining -= take_cost
    filled = remaining <= 1e-6 and shares > 0
    return dict(best_bid=best_bid, best_ask=best_ask, spread=best_ask - best_bid,
                vwap=(spent / shares if shares else best_ask), shares=shares, filled=filled,
                depth=sum(p * s for p, s in asks))

def desired_stake(winp, cost, equity):
    if cost <= 0 or cost >= 1 or winp <= cost:
        return 0.0
    kelly = (winp - cost) / (1.0 - cost)
    frac = min(MAX_SINGLE_FRACTION, KELLY_FRACTION * kelly)
    return equity * frac

def open_group_stake(st, group):
    total = 0.0
    for mid, s in st.get('signaled', {}).items():
        if mid in st.get('settled', {}):
            continue
        if s.get('group') == group:
            total += float(s.get('stake', 0) or 0)
    return total

def discover():
    out = {}
    for name, sym in ASSETS.items():
        try:
            d = http_get(f'https://gamma-api.polymarket.com/public-search?q={name}&limit_per_type=30')
        except Exception as e:
            print('search failed', name, e); continue
        for e in d.get('events', []):
            slug = e.get('slug', '')
            if '-above-on-' in slug:
                kind = 'daily'
            elif slug.startswith('what-price-will-'):
                kind = 'monthly'
            else:
                continue
            for m in e.get('markets', []):
                if m.get('closed'):
                    continue
                q = m.get('question', '')
                mm = re.search(r'\$([\d,]+(?:\.\d+)?)', q)
                if not mm:
                    continue
                K = float(mm.group(1).replace(',', ''))
                ql = q.lower()
                if 'reach' in ql or 'hit' in ql:
                    typ, up = 'touch', True
                elif 'dip' in ql:
                    typ, up = 'touch', False
                elif 'above' in ql:
                    typ, up = 'terminal', True
                elif 'below' in ql:
                    typ, up = 'terminal', False
                else:
                    continue
                try:
                    prices = json.loads(m.get('outcomePrices') or '[]')
                    yes = float(prices[0])
                except Exception:
                    continue
                try:
                    toks = json.loads(m.get('clobTokenIds') or '[]')
                except Exception:
                    toks = []
                mid = str(m.get('id'))
                out[mid] = dict(id=mid, q=q, sym=sym, asset=name, kind=kind, K=K, typ=typ, up=up,
                                yes=yes, end=m.get('endDate'), vol=float(m.get('volume') or 0),
                                token_yes=toks[0] if len(toks) > 0 else None,
                                token_no=toks[1] if len(toks) > 1 else None,
                                event_slug=slug, group=f"{name}|{kind}|{m.get('endDate')}")
    return list(out.values())

CITIES = [
    ('nyc', 40.78, -73.87, 'F'), ('chicago', 41.97, -87.91, 'F'),
    ('los-angeles', 33.94, -118.41, 'F'), ('miami', 25.79, -80.29, 'F'),
    ('dallas', 32.90, -97.04, 'F'), ('seattle', 47.45, -122.31, 'F'),
    ('atlanta', 33.64, -84.43, 'F'), ('toronto', 43.68, -79.63, 'F'),
    ('london', 51.47, -0.45, 'C'), ('paris', 48.97, 2.44, 'C'),
    ('seoul', 37.46, 126.44, 'C'), ('hong-kong', 22.31, 114.17, 'C'),
    ('tokyo', 35.55, 139.78, 'C'), ('sydney', -33.95, 151.18, 'C'),
]
_wx_cache = {}

def parse_bucket(q):
    m = re.search(r'be ([\d.]+)\u00b0[FC] or (below|lower)', q)
    if m: return ('le', float(m.group(1)))
    m = re.search(r'be ([\d.]+)\u00b0[FC] or (higher|above)', q)
    if m: return ('ge', float(m.group(1)))
    m = re.search(r'between ([\d.]+)-([\d.]+)\u00b0[FC]', q)
    if m: return ('range', float(m.group(1)), float(m.group(2)))
    m = re.search(r'be ([\d.]+)\u00b0[FC] on', q)
    if m: return ('eq', float(m.group(1)))
    return None

def bucket_hit(bucket, r):
    t = bucket[0]
    if t == 'le': return r <= bucket[1]
    if t == 'ge': return r >= bucket[1]
    if t == 'range': return bucket[1] <= r <= bucket[2]
    return r == bucket[1]

def ensemble_rounded(lat, lon, unit, datestr, mode):
    key = (lat, lon, unit, datestr, mode)
    if key in _wx_cache:
        return _wx_cache[key]
    tu = 'fahrenheit' if unit == 'F' else 'celsius'
    url = (f'https://ensemble-api.open-meteo.com/v1/ensemble?latitude={lat}&longitude={lon}'
           f'&hourly=temperature_2m&temperature_unit={tu}&forecast_days=10&models=gfs_seamless&timezone=auto')
    try:
        d = http_get(url)
    except Exception:
        _wx_cache[key] = None; return None
    h = d.get('hourly', {})
    times = h.get('time', [])
    idx = [i for i, t in enumerate(times) if t.startswith(datestr)]
    members = []
    for k, vals in h.items():
        if not k.startswith('temperature_2m'):
            continue
        day = [vals[i] for i in idx if vals[i] is not None]
        if len(day) >= 12:
            members.append(max(day) if mode == 'max' else min(day))
    if len(members) < 10:
        _wx_cache[key] = None; return None
    rounded = [int(math.floor(v + 0.5)) for v in members]
    _wx_cache[key] = rounded
    return rounded

def discover_weather():
    from datetime import timedelta
    out = {}
    today = datetime.now(timezone.utc).date()
    for prefix, mode in [('highest-temperature-in-', 'max'), ('lowest-temperature-in-', 'min')]:
        for cslug, lat, lon, unit in CITIES:
            for off in range(-1, 3):
                day = today + timedelta(days=off)
                slug = f"{prefix}{cslug}-on-{day.strftime('%B').lower()}-{day.day}-{day.year}"
                try:
                    evs = http_get(f'https://gamma-api.polymarket.com/events?slug={slug}')
                except Exception:
                    continue
                if not evs:
                    continue
                e = evs[0]
                datestr = day.isoformat()
                rounded = ensemble_rounded(lat, lon, unit, datestr, mode)
                if rounded is None:
                    continue
                n = len(rounded)
                med = float(sorted(rounded)[n // 2])
                for m in e.get('markets', []):
                    if m.get('closed'):
                        continue
                    q = m.get('question', '')
                    bucket = parse_bucket(q)
                    if not bucket:
                        continue
                    try:
                        prices = json.loads(m.get('outcomePrices') or '[]')
                        yes = float(prices[0])
                        toks = json.loads(m.get('clobTokenIds') or '[]')
                    except Exception:
                        continue
                    p = 0.02 + 0.88 * (sum(1 for r in rounded if bucket_hit(bucket, r)) / n)  # ensemble calibration shrink: cap 0.90 / floor 0.02
                    mid = str(m.get('id'))
                    out[mid] = dict(id=mid, q=q, sym=None, asset=f'weather-{cslug}', kind='weather',
                                    K=bucket[-1], typ='weather', up=True, yes=yes, end=m.get('endDate'),
                                    vol=float(m.get('volume') or 0),
                                    token_yes=toks[0] if len(toks) > 0 else None,
                                    token_no=toks[1] if len(toks) > 1 else None,
                                    event_slug=slug, group=f"weather|{cslug}|{datestr}|{mode}",
                                    model_p=p, spot=med, sigma=0.0)
    return list(out.values())

def settle(st, now):
    done = []
    for mid, s in list(st['signaled'].items()):
        if mid in st['settled']:
            continue
        endt = datetime.fromisoformat(s['end'].replace('Z', '+00:00'))
        if endt > now:
            continue
        try:
            m = http_get(f'https://gamma-api.polymarket.com/markets/{mid}')
        except Exception:
            continue
        if not m.get('closed'):
            continue
        try:
            res = float(json.loads(m.get('outcomePrices') or '[]')[0])
        except Exception:
            continue
        win = (s['side'] == 'YES' and res == 1.0) or (s['side'] == 'NO' and res == 0.0)
        stake = float(s.get('stake', 0) or 0)
        shares = float(s.get('shares', 0) or 0)
        side_res = res if s['side'] == 'YES' else 1.0 - res
        pnl = shares * side_res - stake if stake else 0.0
        st['settled'][mid] = {'result': res, 'win': win, 'ts': now.isoformat(), 'stake': stake, 'pnl': round(pnl, 2)}
        st['stats']['n'] += 1
        st['stats']['wins'] += 1 if win else 0
        st['stats']['brier'] += (s['model'] - res) ** 2
        st['stats']['pnl'] = st['stats'].get('pnl', 0.0) + pnl
        st['stats']['staked'] = st['stats'].get('staked', 0.0) + stake
        done.append((s, res, win, pnl))
    return done

def run(send_tg=True):
    now = datetime.now(timezone.utc)
    st = load_state()
    settled = settle(st, now)
    markets = discover()
    try:
        markets = markets + discover_weather()
    except Exception as e:
        print('weather discovery failed:', e)
    print(f'[{now:%Y-%m-%d %H:%M} UTC] scanned {len(markets)} markets; settled {len(settled)}')
    new_sigs = []
    new_watch = []
    filtered = [0]
    for mk in markets:
        if mk['id'] in st['signaled']:
            continue
        endt = datetime.fromisoformat(mk['end'].replace('Z', '+00:00'))
        Tsec = (endt - now).total_seconds()
        if Tsec < 1800 or Tsec > 75 * 86400:
            continue
        if not (0.02 <= mk['yes'] <= 0.98):
            continue
        if 'model_p' in mk:
            p = mk['model_p']; S = mk.get('spot', 0); sig = 0.0
        else:
            S, sig_d, sig_h = spot_vol(mk['sym'])
            T = Tsec / YEAR
            sig = sig_h if Tsec < 2 * 86400 else sig_d
            if mk['typ'] == 'terminal':
                p = p_terminal(S, mk['K'], T, sig, mk['up'])
            else:
                p = p_passage(S, mk['K'], T, sig, mk['up'])
        edge = p - mk['yes']
        if abs(edge) < WATCH_EDGE_MIN:
            continue
        side = 'YES' if edge > 0 else 'NO'
        gamma_cost = mk['yes'] if side == 'YES' else 1.0 - mk['yes']
        winp = p if side == 'YES' else 1.0 - p
        if winp < MIN_WINP or gamma_cost > 0.58:
            filtered[0] += 1
            continue
        token_id = mk.get('token_yes') if side == 'YES' else mk.get('token_no')
        if not token_id:
            filtered[0] += 1
            continue
        equity = BANKROLL + float(st['stats'].get('pnl', 0.0))
        group = mk.get('group') or f"{mk['asset']}|{mk['kind']}|{mk['end']}"
        group_room = max(0.0, equity * MAX_GROUP_FRACTION - open_group_stake(st, group))
        stake0 = min(desired_stake(winp, gamma_cost, equity), group_room)
        if stake0 < MIN_STAKE:
            filtered[0] += 1
            continue
        quote = orderbook_quote(token_id, stake0)
        if not quote or not quote['filled'] or quote['spread'] > MAX_SPREAD:
            filtered[0] += 1
            continue
        cost = quote['vwap']
        exec_edge = winp - cost
        payout = (1.0 - cost) / cost if cost > 0 else 0.0
        ev = winp / cost - 1.0 if cost > 0 else 0.0
        stake = min(desired_stake(winp, cost, equity), group_room, stake0)
        is_formal = exec_edge >= EDGE_MIN and cost <= CHEAP_MAX and winp >= MIN_WINP
        is_watch = (not is_formal) and exec_edge >= WATCH_EDGE_MIN and cost <= WATCH_CHEAP_MAX and winp >= WATCH_MIN_WINP
        if not is_formal and not is_watch:
            filtered[0] += 1
            continue
        rec = dict(id=mk['id'], q=mk['q'], asset=mk['asset'], kind=mk['kind'], K=mk['K'],
                   typ=mk['typ'], up=mk['up'], end=mk['end'], spot=S, sigma=round(sig, 4),
                   model=round(p, 4), market=mk['yes'], side=side,
                   edge=round(exec_edge if side == 'YES' else -exec_edge, 4),
                   gamma_cost=round(gamma_cost, 4), cost=round(cost, 4), winp=round(winp, 4),
                   payout=round(payout, 3), ev=round(ev, 4), best_bid=round(quote['best_bid'], 4),
                   best_ask=round(quote['best_ask'], 4), spread=round(quote['spread'], 4),
                   token_id=token_id, group=group, ts=now.isoformat())
        if is_formal:
            if stake < MIN_STAKE:
                filtered[0] += 1
                continue
            rec['stake'] = round(stake, 2)
            rec['shares'] = round(stake / cost, 4) if cost > 0 else 0.0
            st['signaled'][mk['id']] = rec
            st.get('watchlist', {}).pop(mk['id'], None)
            with open(LEDGER, 'a') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            new_sigs.append(rec)
        else:
            if mk['id'] in st.get('watchlist', {}):
                continue
            st['watchlist'][mk['id']] = rec
            with open(WATCH_LEDGER, 'a') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            new_watch.append(rec)
    save_state(st)
    # Scan results are not pushed anywhere - they are only logged locally.
    # A summary goes out only via the explicit 'daily' command (e.g. from cron).
    if settled:
        # Log settled trades locally but don't send notification
        for s, res, win, pnl in settled:
            logger.info(f"Settled: {s['q'][:60]} -> {int(res)} (model {round(s['model']*100)}% market {round(s['market']*100)}% side {s['side']})")
    
    # Log scan stats locally
    logger.info(f'Scan complete: {len(new_sigs)} new signals, {len(new_watch)} watch, {len(settled)} settled, {filtered[0]} filtered')
    return new_sigs

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'daily':
        daily_report()
    else:
        run(send_tg=('notg' not in sys.argv))
