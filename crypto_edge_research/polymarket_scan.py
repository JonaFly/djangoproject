"""Polymarket scanner: dutch-book (rebalancing) arbitrage, weather-bracket mispricing vs ensemble
forecasts, long-shot NO yield, and Up/Down micro-market cost check.

Data sources (public, no key):
  * gamma-api.polymarket.com /events?active=true&closed=false   -> events + nested markets (bestBid/bestAsk)
  * clob.polymarket.com      /book?token_id=                     -> depth for candidate trades
  * ensemble-api.open-meteo.com /v1/ensemble                     -> GFS 31-member daily Tmax/Tmin
  * geocoding-api.open-meteo.com /v1/search                      -> city -> lat/lon

Fees (Fee Structure V2, 2026; taker only, maker 0): per-share fee = rate * p * (1-p).
Rates by category are configurable; crypto 0.07, sports 0.05 are the published values,
everything else defaults to 0 and MUST be verified on the market page before trading.
"""
from __future__ import annotations

import json
import math
import re
import sys
from datetime import datetime, timezone

from common import get_json, md_table

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
ENSEMBLE = "https://ensemble-api.open-meteo.com/v1/ensemble"
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"

FEE_RATES = {"crypto": 0.07, "sports": 0.05, "default": 0.0}
WEATHER_TITLE = re.compile(r"^(Highest|Lowest) temperature in (.+?) on (\w+ \d{1,2})", re.I)
# Open-Meteo station mismatch + model error; ~1.8F (1C) one-sigma is a conservative day-1..3 figure.
DEFAULT_SIGMA_F = 1.8


# ---------- generic helpers ----------
def taker_fee(price: float, category: str) -> float:
    return FEE_RATES.get(category, FEE_RATES["default"]) * price * (1 - price)


def category_of(event: dict) -> str:
    tags = " ".join(str(t.get("label", t) if isinstance(t, dict) else t) for t in event.get("tags") or []).lower()
    title = (event.get("title") or "").lower()
    if "crypto" in tags or re.search(r"\b(bitcoin|btc|ethereum|eth|solana|sol|xrp)\b", title):
        return "crypto"
    if "sports" in tags or "nba" in tags or "nfl" in tags or "soccer" in tags:
        return "sports"
    return "default"


def _f(x, default=float("nan")) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def days_to(end_iso: str | None) -> float:
    if not end_iso:
        return float("nan")
    end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    return max((end - datetime.now(timezone.utc)).total_seconds() / 86400, 0.01)


def fetch_events(max_pages: int = 60, page: int = 100) -> list[dict]:
    out = []
    for i in range(max_pages):
        batch = get_json(f"{GAMMA}/events", {"active": "true", "closed": "false", "limit": page, "offset": i * page},
                         cache_ttl=300)
        if not batch:
            break
        out += batch
        if len(batch) < page:
            break
    return out


def fetch_book(token_id: str) -> dict:
    return get_json(f"{CLOB}/book", {"token_id": token_id}, cache_ttl=60)


# ---------- 1. dutch book / rebalancing arbitrage ----------
def dutch_book(markets: list[list[float]]) -> dict:
    """markets: [[yes_bid, yes_ask], ...] for mutually-exclusive outcomes where exactly one resolves YES.
    buy_all_yes profit = 1 - sum(ask); sell_all_yes (== buy all NO) profit = sum(bid) - 1. Per-share, pre-fee."""
    asks = [a for _, a in markets if a == a and a > 0]
    bids = [b for b, _ in markets if b == b and b > 0]
    n = len(markets)
    res = {"n": n, "sum_ask": sum(asks) if len(asks) == n else float("nan"),
           "sum_bid": sum(bids) if len(bids) == n else float("nan")}
    res["buy_all_yes_profit"] = 1 - res["sum_ask"]
    res["sell_all_yes_profit"] = res["sum_bid"] - 1
    return res


def scan_dutch_books(events: list[dict], min_profit: float = 0.005) -> list[dict]:
    out = []
    for ev in events:
        ms = ev.get("markets") or []
        if not ev.get("negRisk") or len(ms) < 2:
            continue
        quotes = [[_f(m.get("bestBid")), _f(m.get("bestAsk"))] for m in ms if m.get("active") and not m.get("closed")]
        if len(quotes) < 2:
            continue
        db = dutch_book(quotes)
        cat = category_of(ev)
        fee_yes = sum(taker_fee(a, cat) for _, a in quotes if a == a)
        fee_no = sum(taker_fee(1 - b, cat) for b, _ in quotes if b == b)
        best = max(db["buy_all_yes_profit"] - fee_yes, db["sell_all_yes_profit"] - fee_no)
        if best == best and best >= min_profit:
            out.append({"event": ev.get("title"), "slug": ev.get("slug"), "n_outcomes": db["n"], "category": cat,
                        "sum_ask": db["sum_ask"], "sum_bid": db["sum_bid"], "net_profit_per_set": best,
                        "days_to_end": days_to(ev.get("endDate")),
                        "ann_return_pct": best / max(min(db["sum_ask"], db["sum_bid"]), 0.01) * 365 / days_to(ev.get("endDate")) * 100,
                        "liquidity": sum(_f(m.get("liquidityNum"), 0) for m in ms)})
    return sorted(out, key=lambda r: -r["net_profit_per_set"])


# ---------- 2. weather brackets vs ensemble ----------
_BR = re.compile(r"(?P<a>-?\d+(?:\.\d+)?)\s*(?:°\s*)?(?P<u>[FC])?\s*(?P<rest>.*)", re.I)


def parse_bracket(label: str):
    """'66-67°F' -> (66,67); '≤60°F'/'60°F or below' -> (-inf,60); '72°F or higher' -> (72, inf); '68°F' -> (68,68)."""
    s = label.replace("–", "-").replace("—", "-").strip()
    low_words = ("or below", "or lower", "or less", "or under")
    high_words = ("or above", "or higher", "or more", "or over")
    rng = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*(?:°\s*[FC])?\s*-\s*(-?\d+(?:\.\d+)?)", s)
    if rng:
        return float(rng.group(1)), float(rng.group(2))
    if s.startswith(("≤", "<=")):
        return -math.inf, float(re.search(r"-?\d+(?:\.\d+)?", s).group())
    if s.startswith(("≥", ">=")):
        return float(re.search(r"-?\d+(?:\.\d+)?", s).group()), math.inf
    m = _BR.search(s)
    if not m:
        return None
    v = float(m["a"])
    rest = m["rest"].lower()
    if any(w in rest for w in low_words):
        return -math.inf, v
    if any(w in rest for w in high_words):
        return v, math.inf
    return v, v


def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bracket_probability(members: list[float], lo: float, hi: float, sigma: float = DEFAULT_SIGMA_F,
                        bias: float = 0.0) -> float:
    """Smooth each ensemble member with N(bias, sigma); integer brackets [lo,hi] cover reals [lo-0.5, hi+0.5)."""
    a = -math.inf if lo == -math.inf else lo - 0.5
    b = math.inf if hi == math.inf else hi + 0.5
    tot = 0.0
    for m in members:
        mu = m + bias
        pa = 0.0 if a == -math.inf else _ncdf((a - mu) / sigma)
        pb = 1.0 if b == math.inf else _ncdf((b - mu) / sigma)
        tot += pb - pa
    return tot / len(members) if members else float("nan")


def geocode(city: str) -> tuple[float, float]:
    res = get_json(GEOCODE, {"name": city, "count": 1}, cache_ttl=86400 * 30)
    r = res["results"][0]
    return r["latitude"], r["longitude"]


def fetch_ensemble(lat: float, lon: float, unit: str, models: str = "gfs_seamless") -> dict:
    """Returns {date: {'max': [members], 'min': [members]}} in the requested unit (F or C)."""
    res = get_json(ENSEMBLE, {"latitude": lat, "longitude": lon, "daily": "temperature_2m_max,temperature_2m_min",
                              "models": models, "timezone": "auto", "forecast_days": 10,
                              "temperature_unit": "fahrenheit" if unit == "F" else "celsius"}, cache_ttl=3 * 3600)
    daily = res["daily"]
    out = {}
    for i, d in enumerate(daily["time"]):
        out[d] = {"max": [v[i] for k, v in daily.items() if k.startswith("temperature_2m_max") and v[i] is not None],
                  "min": [v[i] for k, v in daily.items() if k.startswith("temperature_2m_min") and v[i] is not None]}
    return out


def weather_edges(events: list[dict], min_edge: float = 0.08, sigma_f: float = DEFAULT_SIGMA_F) -> list[dict]:
    out = []
    year = datetime.now(timezone.utc).year
    for ev in events:
        m = WEATHER_TITLE.match(ev.get("title") or "")
        if not m:
            continue
        kind, city, datestr = m.group(1).lower(), m.group(2).strip(), m.group(3)
        try:
            day = datetime.strptime(f"{datestr} {year}", "%B %d %Y").date().isoformat()
        except ValueError:
            continue
        unit = "C" if any("°C" in (mk.get("groupItemTitle") or "") for mk in ev.get("markets") or []) else "F"
        try:
            lat, lon = geocode(city)
            ens = fetch_ensemble(lat, lon, unit)
        except Exception as exc:
            out.append({"event": ev.get("title"), "error": str(exc)})
            continue
        if day not in ens:
            continue
        members = ens[day]["max" if kind == "highest" else "min"]
        sigma = sigma_f if unit == "F" else sigma_f / 1.8
        for mk in ev.get("markets") or []:
            br = parse_bracket(mk.get("groupItemTitle") or mk.get("question") or "")
            if not br:
                continue
            p = bracket_probability(members, *br, sigma=sigma)
            bid, ask = _f(mk.get("bestBid")), _f(mk.get("bestAsk"))
            cat = "default"
            ev_yes = p - ask - taker_fee(ask, cat) if ask == ask else float("nan")
            ev_no = (1 - p) - (1 - bid) - taker_fee(1 - bid, cat) if bid == bid else float("nan")
            side, edge = ("YES", ev_yes) if (ev_yes == ev_yes and ev_yes >= ev_no) else ("NO", ev_no)
            if edge == edge and edge >= min_edge:
                out.append({"event": ev.get("title"), "bracket": mk.get("groupItemTitle"), "model_p": p,
                            "bid": bid, "ask": ask, "side": side, "net_edge": edge, "n_members": len(members),
                            "liquidity": _f(mk.get("liquidityNum"), 0), "token_ids": mk.get("clobTokenIds")})
    return sorted(out, key=lambda r: -r.get("net_edge", -1))


# ---------- 3. long-shot NO yield ----------
def longshot_no_yield(events: list[dict], max_yes_ask: float = 0.05, min_days: float = 1) -> list[dict]:
    out = []
    for ev in events:
        cat = category_of(ev)
        for mk in ev.get("markets") or []:
            ask, bid = _f(mk.get("bestAsk")), _f(mk.get("bestBid"))
            d = days_to(mk.get("endDate") or ev.get("endDate"))
            if not (ask == ask and bid == bid) or ask > max_yes_ask or d < min_days or bid <= 0:
                continue
            no_cost = 1 - bid + taker_fee(1 - bid, cat)
            gross = 1 / no_cost - 1
            out.append({"market": mk.get("question"), "yes_ask": ask, "no_cost": no_cost, "days": d,
                        "simple_return_pct": gross * 100, "ann_return_pct": gross * 365 / d * 100,
                        "liquidity": _f(mk.get("liquidityNum"), 0), "category": cat})
    return sorted(out, key=lambda r: -r["ann_return_pct"])


# ---------- 4. Up/Down micro-markets ----------
def updown_summary(events: list[dict]) -> dict:
    spreads, fees, n = [], [], 0
    for ev in events:
        if "up or down" not in (ev.get("title") or "").lower():
            continue
        for mk in ev.get("markets") or []:
            bid, ask = _f(mk.get("bestBid")), _f(mk.get("bestAsk"))
            if bid == bid and ask == ask:
                n += 1
                spreads.append(ask - bid)
                fees.append(taker_fee((bid + ask) / 2, "crypto"))
    return {"n_markets": n, "mean_spread": sum(spreads) / n if n else float("nan"),
            "mean_taker_fee_per_share": sum(fees) / n if n else float("nan"),
            "roundtrip_cost_per_share": (sum(spreads) + 2 * sum(fees)) / n if n else float("nan")}


def run() -> dict:
    events = fetch_events()
    return {"n_events": len(events), "dutch_books": scan_dutch_books(events)[:20],
            "weather": weather_edges(events)[:30], "longshots": longshot_no_yield(events)[:20],
            "updown": updown_summary(events)}


def to_markdown(res: dict) -> str:
    u = res["updown"]
    lines = [f"### Polymarket 扫描 ({res['n_events']} 个活跃事件)", "",
             "#### 1. 多结果事件 dutch book (扣费后每套 ≥ 0.5c)",
             md_table(["事件", "结果数", "类别", "ΣAsk", "ΣBid", "每套净利", "剩余天", "年化 %", "流动性 $"],
                      [[d["event"], d["n_outcomes"], d["category"], d["sum_ask"], d["sum_bid"], d["net_profit_per_set"],
                        d["days_to_end"], d["ann_return_pct"], d["liquidity"]] for d in res["dutch_books"]]) or "(无)",
             "", "#### 2. 天气区间 vs GFS 31 成员集合预报 (净边际 ≥ 8c)",
             md_table(["事件", "区间", "模型 p", "Bid", "Ask", "方向", "净边际", "成员数", "流动性 $"],
                      [[w.get("event"), w.get("bracket"), w.get("model_p"), w.get("bid"), w.get("ask"), w.get("side"),
                        w.get("net_edge"), w.get("n_members"), w.get("liquidity")] for w in res["weather"] if "error" not in w]),
             "", "#### 3. 长尾 NO (YES ask ≤ 5c) 年化收益 — 注意 UMA 裁决风险",
             md_table(["市场", "YES ask", "NO 成本", "天数", "简单收益 %", "年化 %", "流动性 $", "类别"],
                      [[l["market"], l["yes_ask"], l["no_cost"], l["days"], l["simple_return_pct"], l["ann_return_pct"],
                        l["liquidity"], l["category"]] for l in res["longshots"]]),
             "", "#### 4. 15 分钟/5 分钟 Up-or-Down 市场成本",
             md_table(["指标", "值"], [["市场数", u["n_markets"]], ["平均价差", u["mean_spread"]],
                                       ["平均 taker 费/股 (7%×p(1-p))", u["mean_taker_fee_per_share"]],
                                       ["来回总成本/股", u["roundtrip_cost_per_share"]]])]
    return "\n".join(lines)


if __name__ == "__main__":
    res = run()
    print(to_markdown(res))
    if "--json" in sys.argv:
        print(json.dumps(res, indent=1, default=str))
