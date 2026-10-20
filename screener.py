"""Pre-market screener for NSE stocks (1-2 day trades).
Run:  python screener.py          -> real data, writes docs/index.html + docs/data.json
      python screener.py --demo   -> synthetic data (to test without internet)
Educational tool. Not investment advice. Picks are rule-based, never guaranteed.
"""
import sys, json, math, html, datetime as dt
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd

# ---------------- SETTINGS (edit these) ----------------
CAPITAL = 100_000          # your money in Rs
RISK_PER_TRADE = 0.01      # risk 1% of capital (Rs 1,000) per trade
MAX_POSITIONS = 3          # max trades at once; capital split equally
STOP_ATR = 1.0             # stop-loss distance = 1 x ATR
TARGET_ATR = 1.5           # target distance = 1.5 x ATR
MIN_SCORE = 4              # minimum score (out of 6) to be listed
DAILY_LOSS_LIMIT = 0.02    # stop trading for the day if you lose 2% (Rs 2,000)
UNIVERSE = """RELIANCE TCS HDFCBANK ICICIBANK INFY BHARTIARTL ITC SBIN LT HINDUNILVR
KOTAKBANK AXISBANK BAJFINANCE MARUTI SUNPHARMA TITAN NTPC ONGC TATASTEEL ADANIENT
ADANIPORTS ASIANPAINT ULTRACEMCO POWERGRID WIPRO HCLTECH TECHM M&M NESTLEIND JSWSTEEL
COALINDIA BAJAJFINSV GRASIM HINDALCO CIPLA DRREDDY EICHERMOT HEROMOTOCO BPCL
INDUSINDBK APOLLOHOSP BRITANNIA TRENT SBILIFE HDFCLIFE BEL SHRIRAMFIN""".split()
GLOBAL = {"Nifty 50": "^NSEI", "Sensex": "^BSESN", "India VIX": "^INDIAVIX",
          "S&P 500": "^GSPC", "Nasdaq": "^IXIC", "Nikkei": "^N225",
          "Crude (WTI)": "CL=F", "USD/INR": "INR=X"}
BAD_WORDS = ["fraud", "probe", "raid", "downgrade", "penalty", "resigns", "resign", "default",
             "sebi order", "ban", "lawsuit", "plunge", "slump", "cuts target", "investigation"]
# -------------------------------------------------------
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
DEMO = "--demo" in sys.argv


def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(df, n=14):
    pc = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def download(tickers):
    if DEMO:
        rng = np.random.default_rng(7)
        idx = pd.bdate_range(end=pd.Timestamp.today(), periods=130)
        cols = {}
        for t in tickers:
            c = 1000 * np.exp(np.cumsum(rng.normal(0.0005, 0.013, len(idx))))
            o = c * (1 + rng.normal(0, 0.004, len(idx)))
            h = np.maximum(o, c) * (1 + abs(rng.normal(0, 0.006, len(idx))))
            l = np.minimum(o, c) * (1 - abs(rng.normal(0, 0.006, len(idx))))
            v = rng.integers(1_000_000, 5_000_000, len(idx)).astype(float)
            for k, a in zip(["Open", "High", "Low", "Close", "Volume"], [o, h, l, c, v]):
                cols[(t, k)] = a
        return pd.DataFrame(cols, index=idx)
    import yfinance as yf
    return yf.download(tickers, period="6mo", interval="1d", group_by="ticker",
                       auto_adjust=True, progress=False, threads=True)


def global_cues():
    raw = download(list(GLOBAL.values()))
    out = []
    for name, t in GLOBAL.items():
        try:
            c = raw[t]["Close"].dropna()
            out.append({"name": name, "value": round(float(c.iloc[-1]), 2),
                        "chg": round(float(c.iloc[-1] / c.iloc[-2] - 1) * 100, 2)})
        except Exception:
            pass
    return out


def analyze(sym, df):
    df = df.dropna()
    if len(df) < 60:
        return None
    c = df["Close"]
    last, prev = float(c.iloc[-1]), float(c.iloc[-2])
    sma20, sma50 = float(c.rolling(20).mean().iloc[-1]), float(c.rolling(50).mean().iloc[-1])
    r, a = float(rsi(c).iloc[-1]), float(atr(df).iloc[-1])
    vr = float(df["Volume"].iloc[-1] / df["Volume"].rolling(20).mean().iloc[-1])
    chg = (last / prev - 1) * 100
    hi, lo = float(df["High"].iloc[-1]), float(df["Low"].iloc[-1])
    pos = (last - lo) / (hi - lo) if hi > lo else 0.5
    b, s, wb, ws = 0, 0, [], []
    if last > sma20 > sma50: b += 2; wb.append("Uptrend: price above 20 and 50 day averages")
    if last < sma20 < sma50: s += 2; ws.append("Downtrend: price below 20 and 50 day averages")
    if 50 <= r <= 68: b += 1; wb.append(f"RSI {r:.0f}: strong but not overheated")
    if 32 <= r <= 50: s += 1; ws.append(f"RSI {r:.0f}: weak momentum")
    if r > 75: b -= 2; wb.append(f"RSI {r:.0f}: overbought, risky")
    if r < 25: s -= 2; ws.append(f"RSI {r:.0f}: oversold, bounce risk")
    if vr >= 1.2 and chg > 0: b += 1; wb.append(f"Volume {vr:.1f}x average on a green day")
    if vr >= 1.2 and chg < 0: s += 1; ws.append(f"Volume {vr:.1f}x average on a red day")
    if 0.5 <= chg <= 4: b += 1; wb.append(f"Up {chg:.1f}% yesterday")
    if -4 <= chg <= -0.5: s += 1; ws.append(f"Down {abs(chg):.1f}% yesterday")
    if pos >= 0.7: b += 1; wb.append("Closed near the day's high")
    if pos <= 0.3: s += 1; ws.append("Closed near the day's low")
    return {"symbol": sym, "price": last, "atr": a, "chg": chg, "rsi": r, "vol_ratio": vr,
            "buy": b, "sell": s, "why_buy": wb, "why_sell": ws}


def news(query, n=3):
    try:
        url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(query) + "&hl=en-IN&gl=IN&ceid=IN:en"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=15) as f:
            root = ET.fromstring(f.read())
        return [i.findtext("title") for i in root.iter("item")][:n]
    except Exception:
        return []


def plan(p, side, size_factor):
    e, a = p["price"], p["atr"]
    risk = STOP_ATR * a
    stop = e - risk if side == "BUY" else e + risk
    target = e + TARGET_ATR * a if side == "BUY" else e - TARGET_ATR * a
    qty = math.floor(min(RISK_PER_TRADE * CAPITAL * size_factor / risk, CAPITAL / MAX_POSITIONS / e))
    return {"entry": round(e, 2), "stop": round(stop, 2), "target": round(target, 2), "qty": qty,
            "invest": round(qty * e), "max_loss": round(qty * risk), "profit": round(qty * TARGET_ATR * a)}


def pick(rows, key, side, min_score, size_factor):
    out = []
    for p in sorted([r for r in rows if r[key] >= min_score], key=lambda r: -r[key])[:MAX_POSITIONS]:
        q = plan(p, side, size_factor)
        if q["qty"] < 1:
            continue
        h = [] if DEMO else news(p["symbol"].replace("&", "and") + " share NSE")
        flag = any(w in t.lower() for t in h for w in BAD_WORDS)
        out.append({**p, **q, "side": side, "score": p[key], "reasons": p["why_buy" if side == "BUY" else "why_sell"],
                    "headlines": h, "news_flag": flag})
    return out


def run():
    tick = [s + ".NS" for s in UNIVERSE]
    raw = download(tick)
    rows = []
    for s, t in zip(UNIVERSE, tick):
        try:
            r = analyze(s, raw[t][["Open", "High", "Low", "Close", "Volume"]])
            if r: rows.append(r)
        except Exception:
            continue
    cues = global_cues()
    g = {c["name"]: c["chg"] for c in cues}
    world = np.mean([g.get(k, 0) for k in ["S&P 500", "Nasdaq", "Nikkei"]])
    vix = next((c["value"] for c in cues if c["name"] == "India VIX"), 15)
    mood = "positive" if world > 0.3 else "negative" if world < -0.3 else "mixed"
    size_factor = 0.5 if vix > 20 else 1.0
    buy_min = MIN_SCORE + (1 if mood == "negative" else 0)
    sell_min = MIN_SCORE + (1 if mood == "positive" else 0)
    warnings = []
    if mood == "negative": warnings.append("Global markets are weak. Buy picks need a higher score today.")
    if mood == "positive": warnings.append("Global markets are strong. Short picks need a higher score today.")
    if vix > 20: warnings.append(f"India VIX is {vix}. Position sizes are halved today.")
    data = {"date": dt.datetime.now(IST).strftime("%A, %d %B %Y"), "updated": dt.datetime.now(IST).strftime("%H:%M IST"),
            "mood": mood, "cues": cues, "warnings": warnings, "demo": DEMO,
            "market_news": [] if DEMO else news("Sensex Nifty today market", 4),
            "buys": pick(rows, "buy", "BUY", buy_min, size_factor),
            "sells": pick(rows, "sell", "SELL", sell_min, size_factor),
            "capital": CAPITAL, "loss_limit": round(CAPITAL * DAILY_LOSS_LIMIT)}
    return data


CSS = """
:root{--bg:#eef1f4;--panel:#fff;--ink:#14202b;--mute:#5b6b7a;--line:#d5dce3;--buy:#0b7a5a;--sell:#b3362b;--warn:#8a5a00;--warnbg:#fff3d6}
@media (prefers-color-scheme:dark){:root{--bg:#10171e;--panel:#18222b;--ink:#e7edf2;--mute:#9aabba;--line:#2a3a47;--buy:#3ecf9e;--sell:#ff8a7d;--warn:#ffd27a;--warnbg:#3a2e12}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 'IBM Plex Sans',system-ui,sans-serif;padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}
main{max-width:760px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:1.7rem;line-height:1.2;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:1.2rem;margin:32px 0 12px}
.sub{color:var(--mute);margin:0 0 16px}
.warn{background:var(--warnbg);color:var(--warn);padding:10px 12px;border-radius:6px;margin:8px 0;font-size:.95rem}
.cues{display:flex;gap:10px;overflow-x:auto;padding:4px 0 8px}
.cue{flex:0 0 auto;border-left:3px solid var(--line);padding:0 10px}
.cue b{display:block;font-variant-numeric:tabular-nums}
.up{color:var(--buy)}.down{color:var(--sell)}
.pick{background:var(--panel);border:1px solid var(--line);border-left:5px solid var(--buy);border-radius:4px;padding:14px;margin:12px 0}
.pick.s{border-left-color:var(--sell)}
.top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.sym{font-size:1.35rem;font-weight:700}
.score{color:var(--mute);font-size:.9rem}
.lv{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0}
.lv div{font-size:.8rem;color:var(--mute)}.lv b{display:block;font-size:1.05rem;color:var(--ink);font-variant-numeric:tabular-nums}
.meta{font-size:.92rem;color:var(--mute);margin:0 0 8px}
ul{margin:6px 0;padding-left:18px}li{margin:2px 0;font-size:.93rem}
.news{font-size:.85rem;color:var(--mute)}
.empty{padding:16px;border:1px dashed var(--line);border-radius:4px;color:var(--mute)}
.rules{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:12px 16px}
.fine{color:var(--mute);font-size:.82rem;margin-top:28px}
"""


def e(x): return html.escape(str(x))


def card(p):
    s = "s" if p["side"] == "SELL" else ""
    verb = "Sell (intraday short)" if s else "Buy"
    exitv = "Cover" if s else "Sell"
    reasons = "".join(f"<li>{e(r)}</li>" for r in p["reasons"])
    news_html = "".join(f"<li>{e(h)}</li>" for h in p["headlines"])
    flag = '<div class="warn">A headline today has a risk keyword. Read the news before trading this one.</div>' if p["news_flag"] else ""
    return f"""<section class="pick {s}"><div class="top"><span class="sym">{e(p['symbol'])}</span><span class="score">{verb} · score {p['score']}/6</span></div>
<div class="lv"><div>Entry near<b>₹{p['entry']:,.2f}</b></div><div>Stop-loss<b>₹{p['stop']:,.2f}</b></div><div>{exitv} target<b>₹{p['target']:,.2f}</b></div></div>
<p class="meta">Quantity {p['qty']} · invest ₹{p['invest']:,} · max loss ₹{p['max_loss']:,} · target profit ₹{p['profit']:,}</p>
<ul>{reasons}</ul>{flag}{'<div class="news">Headlines<ul>'+news_html+'</ul></div>' if news_html else ''}</section>"""


def section(title, items, empty):
    return f"<h2>{title}</h2>" + ("".join(card(p) for p in items) if items else f'<div class="empty">{empty}</div>')


def render(d):
    cues = "".join(f"<div class='cue'>{e(c['name'])}<b>{c['value']:,}</b><span class='{'up' if c['chg']>=0 else 'down'}'>{c['chg']:+.2f}%</span></div>" for c in d["cues"])
    warns = "".join(f"<div class='warn'>{e(w)}</div>" for w in d["warnings"])
    if d["demo"]: warns += "<div class='warn'>DEMO DATA. These are random numbers, not real prices.</div>"
    mn = "".join(f"<li>{e(h)}</li>" for h in d["market_news"])
    tot = sum(p["profit"] for p in d["buys"] + d["sells"])
    body = f"""<main><h1>Pre-market plan</h1><p class="sub">{e(d['date'])} · updated {e(d['updated'])} · global mood: {e(d['mood'])}</p>
{warns}<div class="cues">{cues}</div>
{section('Buy ideas (1–2 day hold)', d['buys'], 'No strong buy setup today. Staying in cash is a valid trade.')}
{section('Sell ideas (intraday short only)', d['sells'], 'No strong sell setup today.')}
<h2>Risk rules for today</h2><div class="rules"><ul>
<li>If every target is hit, profit is about ₹{tot:,}. Most days will not go that way.</li>
<li>Place the stop-loss order as soon as you enter. Never move it further away.</li>
<li>If you lose ₹{d['loss_limit']:,} in a day, stop trading until tomorrow.</li>
<li>Selling a stock you do not own must be closed the same day. Held-overnight trades can only be buys.</li>
<li>Skip any trade if the stock opens more than 1.5% away from the entry price.</li></ul></div>
{('<h2>Market headlines</h2><ul>'+mn+'</ul>') if mn else ''}
<p class="fine">Rule-based screen using yesterday's prices, volume, trends and news keywords. It cannot predict gaps or events. Educational use only, not investment advice. Most retail short-term traders lose money. Consult a SEBI-registered advisor.</p></main>"""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pre-market plan {e(d['date'])}</title><style>{CSS}</style></head><body>{body}</body></html>"""


if __name__ == "__main__":
    import os
    d = run()
    os.makedirs("docs", exist_ok=True)
    json.dump(d, open("docs/data.json", "w"), indent=2, default=float)
    open("docs/index.html", "w", encoding="utf-8").write(render(d))
    print("Done:", len(d["buys"]), "buy ideas,", len(d["sells"]), "sell ideas")
