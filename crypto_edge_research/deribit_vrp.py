"""Deribit: implied-vs-realized volatility (variance risk premium), term structure and skew.

Data sources (all public, no API key):
  * /public/get_volatility_index_data   -> DVOL (30d implied vol index) daily history
  * /public/get_tradingview_chart_data  -> BTC-PERPETUAL daily closes for realized vol
  * /public/get_book_summary_by_currency -> full option chain with mark_iv / bid / ask / OI

Output: dict with VRP statistics, a regime flag, and per-expiry ATM IV + 25-delta skew.
"""
from __future__ import annotations

import math
import re
import sys
from datetime import datetime, timezone

from common import bs_delta, get_json, md_table, nanmean, now_ms, rolling_realized_vol

BASE = "https://www.deribit.com/api/v2"
DAY_MS = 86_400_000
_INSTR = re.compile(r"^(?P<ccy>[A-Z]+)-(?P<exp>\d{1,2}[A-Z]{3}\d{2})-(?P<strike>\d+(?:d\d+)?)-(?P<cp>[CP])$")


def fetch_dvol(currency: str = "BTC", days: int = 400) -> list[tuple[int, float]]:
    end = now_ms()
    out: list[tuple[int, float]] = []
    start = end - days * DAY_MS
    while start < end:
        chunk_end = min(end, start + 900 * DAY_MS)
        res = get_json(f"{BASE}/public/get_volatility_index_data",
                       {"currency": currency, "start_timestamp": start, "end_timestamp": chunk_end,
                        "resolution": 86400}, cache_ttl=3600)
        out += [(row[0], float(row[4])) for row in res["result"]["data"]]
        start = chunk_end
    return sorted(set(out))


def fetch_daily_closes(instrument: str = "BTC-PERPETUAL", days: int = 400) -> list[tuple[int, float]]:
    end = now_ms()
    res = get_json(f"{BASE}/public/get_tradingview_chart_data",
                   {"instrument_name": instrument, "start_timestamp": end - days * DAY_MS,
                    "end_timestamp": end, "resolution": "1D"}, cache_ttl=3600)
    r = res["result"]
    return list(zip(r["ticks"], map(float, r["close"])))


def fetch_option_chain(currency: str = "BTC") -> list[dict]:
    res = get_json(f"{BASE}/public/get_book_summary_by_currency",
                   {"currency": currency, "kind": "option"}, cache_ttl=600)
    return res["result"]


def vrp_statistics(dvol: list[tuple[int, float]], closes: list[tuple[int, float]], window: int = 30) -> dict:
    """Align DVOL(t) with realized vol over [t, t+30d] (forward) and [t-30d, t] (trailing)."""
    close_vals = [c for _, c in closes]
    trailing = rolling_realized_vol(close_vals, window)
    close_idx = {ts // DAY_MS: i for i, (ts, _) in enumerate(closes)}
    fwd_rv, trail_rv, iv = [], [], []
    for ts, v in dvol:
        i = close_idx.get(ts // DAY_MS)
        if i is None:
            continue
        iv.append(v)
        trail_rv.append(trailing[i])
        j = i + window
        if j < len(close_vals):
            from common import realized_vol
            fwd_rv.append(realized_vol(close_vals[i:j + 1], 365))
        else:
            fwd_rv.append(float("nan"))
    pairs = [(a, b) for a, b in zip(iv, fwd_rv) if not math.isnan(b)]
    prem = [a - b for a, b in pairs]
    hit = sum(1 for p in prem if p > 0) / len(prem) if prem else float("nan")
    latest_iv = iv[-1] if iv else float("nan")
    latest_trail = next((x for x in reversed(trail_rv) if not math.isnan(x)), float("nan"))
    ivs_sorted = sorted(iv)
    pct_rank = (sum(1 for x in ivs_sorted if x <= latest_iv) / len(ivs_sorted) * 100) if iv else float("nan")
    return {
        "obs_days": len(pairs),
        "mean_iv": nanmean(iv),
        "mean_fwd_rv": nanmean([b for _, b in pairs]),
        "mean_vrp_volpts": nanmean(prem),
        "vrp_hit_rate": hit,
        "worst_vrp_volpts": min(prem) if prem else float("nan"),
        "latest_dvol": latest_iv,
        "latest_trailing_rv": latest_trail,
        "latest_spread_volpts": latest_iv - latest_trail,
        "dvol_percentile_1y": pct_rank,
    }


def regime_flag(stats: dict, min_spread: float = 8.0, min_pct: float = 30.0) -> str:
    """Short-vol deploy filter: need IV-RV spread >= min_spread vol pts AND DVOL not in the bottom decile."""
    s, p = stats["latest_spread_volpts"], stats["dvol_percentile_1y"]
    if math.isnan(s) or math.isnan(p):
        return "UNKNOWN"
    if s >= min_spread and p >= min_pct:
        return "DEPLOY_SHORT_VOL"
    if s <= 0:
        return "NO_PREMIUM_STAND_ASIDE"
    return "THIN_PREMIUM_WAIT"


def parse_instrument(name: str):
    m = _INSTR.match(name)
    if not m:
        return None
    exp = datetime.strptime(m["exp"], "%d%b%y").replace(hour=8, tzinfo=timezone.utc)
    strike = float(m["strike"].replace("d", "."))
    return exp, strike, m["cp"] == "C"


def term_structure(chain: list[dict], max_expiries: int = 8) -> list[dict]:
    now = datetime.now(timezone.utc)
    by_exp: dict[datetime, list] = {}
    for row in chain:
        p = parse_instrument(row["instrument_name"])
        if not p or not row.get("mark_iv"):
            continue
        exp, k, is_call = p
        by_exp.setdefault(exp, []).append((k, is_call, float(row["mark_iv"]), row.get("underlying_price"),
                                           row.get("open_interest", 0), row.get("bid_price"), row.get("ask_price")))
    out = []
    for exp in sorted(by_exp)[:max_expiries]:
        rows = by_exp[exp]
        t = max((exp - now).total_seconds() / (365 * 86400), 1e-6)
        spot = nanmean([r[3] for r in rows if r[3]])
        atm = min(rows, key=lambda r: abs(r[0] - spot))
        puts = [(abs(bs_delta(spot, k, t, iv / 100, False) + 0.25), iv) for k, c, iv, *_ in rows if not c]
        calls = [(abs(bs_delta(spot, k, t, iv / 100, True) - 0.25), iv) for k, c, iv, *_ in rows if c]
        p25 = min(puts)[1] if puts else float("nan")
        c25 = min(calls)[1] if calls else float("nan")
        # bid/ask in BTC: rough width of the ATM market in vol-space is useful but we keep $ width
        atm_ba = (atm[6] - atm[5]) * spot if atm[5] and atm[6] else float("nan")
        out.append({"expiry": exp.date().isoformat(), "days": round(t * 365, 1), "atm_iv": atm[2],
                    "put25_iv": p25, "call25_iv": c25, "skew25": p25 - c25,
                    "oi_contracts": sum(r[4] for r in rows), "atm_spread_usd": atm_ba})
    return out


def run(currency: str = "BTC") -> dict:
    dvol = fetch_dvol(currency)
    closes = fetch_daily_closes(f"{currency}-PERPETUAL")
    stats = vrp_statistics(dvol, closes)
    stats["regime"] = regime_flag(stats)
    chain = fetch_option_chain(currency)
    ts = term_structure(chain)
    return {"currency": currency, "vrp": stats, "term_structure": ts, "n_instruments": len(chain)}


def to_markdown(res: dict) -> str:
    v = res["vrp"]
    lines = [f"### Deribit {res['currency']} 波动率风险溢价 (VRP)",
             md_table(["指标", "值"], [
                 ["样本天数 (DVOL vs 后 30 日已实现波动率)", v["obs_days"]],
                 ["均值 DVOL", v["mean_iv"]], ["均值 后 30 日 RV", v["mean_fwd_rv"]],
                 ["均值 VRP (vol pts)", v["mean_vrp_volpts"]], ["IV > 后续 RV 的比例", v["vrp_hit_rate"]],
                 ["最差单日 VRP", v["worst_vrp_volpts"]], ["最新 DVOL", v["latest_dvol"]],
                 ["最新 30 日 RV", v["latest_trailing_rv"]], ["最新 IV-RV", v["latest_spread_volpts"]],
                 ["DVOL 一年分位", v["dvol_percentile_1y"]], ["部署信号", v["regime"]]]),
             "", f"### 期限结构与 25-delta 偏度 ({res['n_instruments']} 个合约)",
             md_table(["到期", "天数", "ATM IV", "25d Put IV", "25d Call IV", "Skew", "OI", "ATM 价差 $"],
                      [[t["expiry"], t["days"], t["atm_iv"], t["put25_iv"], t["call25_iv"], t["skew25"],
                        t["oi_contracts"], t["atm_spread_usd"]] for t in res["term_structure"]])]
    return "\n".join(lines)


if __name__ == "__main__":
    print(to_markdown(run(sys.argv[1] if len(sys.argv) > 1 else "BTC")))
