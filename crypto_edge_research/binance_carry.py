"""Binance + Deribit: perpetual funding carry and dated-futures basis (cash-and-carry).

Data sources (public):
  * fapi.binance.com /fapi/v1/fundingRate      -> 8h funding history (USDT-M perp)
  * fapi.binance.com /fapi/v1/premiumIndex     -> mark/index for perp and BTCUSDT_<yymmdd> delivery contracts
  * www.deribit.com  /public/get_book_summary_by_currency?kind=future -> dated futures basis cross-check

Net carry = gross annualised yield - fee drag amortised over the holding period.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from common import annualize_rate, get_json, md_table, nanmean

FAPI = "https://fapi.binance.com"
DERIBIT = "https://www.deribit.com/api/v2"
FUNDINGS_PER_YEAR = 3 * 365
# Binance USDT-M taker 0.05% / maker 0.02%; spot taker 0.1% (VIP0). Round trip = 2 legs x open+close.
DEFAULT_FEES = {"perp_taker": 0.0005, "spot_taker": 0.0010}


def fetch_funding(symbol: str = "BTCUSDT", limit: int = 1000) -> list[dict]:
    rows = get_json(f"{FAPI}/fapi/v1/fundingRate", {"symbol": symbol, "limit": limit}, cache_ttl=1800)
    return [{"t": r["fundingTime"], "rate": float(r["fundingRate"])} for r in rows]


def fetch_premium_index() -> list[dict]:
    return get_json(f"{FAPI}/fapi/v1/premiumIndex", cache_ttl=300)


def fetch_deribit_futures(currency: str = "BTC") -> list[dict]:
    return get_json(f"{DERIBIT}/public/get_book_summary_by_currency", {"currency": currency, "kind": "future"},
                    cache_ttl=300)["result"]


def funding_summary(rows: list[dict]) -> dict:
    rates = [r["rate"] for r in rows]
    def ann(n):
        sl = rates[-n:] if n else rates
        return annualize_rate(nanmean(sl), FUNDINGS_PER_YEAR) * 100 if sl else float("nan")
    neg_share = sum(1 for r in rates if r < 0) / len(rates) if rates else float("nan")
    return {"n": len(rates), "last_8h_pct": rates[-1] * 100 if rates else float("nan"),
            "ann_7d_pct": ann(21), "ann_30d_pct": ann(90), "ann_90d_pct": ann(270), "ann_all_pct": ann(0),
            "negative_share": neg_share, "worst_8h_pct": min(rates) * 100 if rates else float("nan")}


def dated_basis(mark: float, index: float, expiry: datetime, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    days = max((expiry - now).total_seconds() / 86400, 0.01)
    raw = mark / index - 1
    return {"days": days, "basis_pct": raw * 100, "ann_basis_pct": raw * 365 / days * 100}


def net_carry(gross_ann_pct: float, holding_days: float, fees: dict = DEFAULT_FEES) -> float:
    """Subtract round-trip fee drag (buy spot + sell perp/future, later unwind both) amortised over holding."""
    drag = 2 * (fees["perp_taker"] + fees["spot_taker"])  # open + close on both legs
    return gross_ann_pct - drag * 365 / holding_days * 100


def binance_dated(premium_rows: list[dict]) -> list[dict]:
    out = []
    for r in premium_rows:
        sym = r["symbol"]
        if not sym.startswith("BTCUSDT_"):
            continue
        exp = datetime.strptime(sym.split("_")[1], "%y%m%d").replace(hour=8, tzinfo=timezone.utc)
        b = dated_basis(float(r["markPrice"]), float(r["indexPrice"]), exp)
        out.append({"venue": "Binance", "symbol": sym, **b, "net_ann_pct": net_carry(b["ann_basis_pct"], b["days"])})
    return sorted(out, key=lambda x: x["days"])


def deribit_dated(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        name = r["instrument_name"]
        if name.endswith("PERPETUAL"):
            continue
        exp = datetime.strptime(name.split("-")[1], "%d%b%y").replace(hour=8, tzinfo=timezone.utc)
        idx = r.get("underlying_price") or r.get("estimated_delivery_price")
        if not idx or not r.get("mark_price"):
            continue
        b = dated_basis(float(r["mark_price"]), float(idx), exp)
        out.append({"venue": "Deribit", "symbol": name, **b,
                    "net_ann_pct": net_carry(b["ann_basis_pct"], b["days"], {"perp_taker": 0.0005, "spot_taker": 0.001})})
    return sorted(out, key=lambda x: x["days"])


def run(symbol: str = "BTCUSDT") -> dict:
    fund = funding_summary(fetch_funding(symbol))
    prem = fetch_premium_index()
    perp = next((r for r in prem if r["symbol"] == symbol), None)
    fund["current_predicted_8h_pct"] = float(perp["lastFundingRate"]) * 100 if perp else float("nan")
    dated = binance_dated(prem)
    try:
        dated += deribit_dated(fetch_deribit_futures(symbol[:3]))
    except Exception as exc:  # cross-check only
        dated.append({"venue": "Deribit", "symbol": f"error: {exc}", "days": float("nan"), "basis_pct": float("nan"),
                      "ann_basis_pct": float("nan"), "net_ann_pct": float("nan")})
    fund["net_30d_carry_pct_90d_hold"] = net_carry(fund["ann_30d_pct"], 90)
    return {"symbol": symbol, "funding": fund, "dated": dated}


def to_markdown(res: dict) -> str:
    f = res["funding"]
    return "\n".join([
        f"### {res['symbol']} 永续资金费率 carry (Binance USDT-M)",
        md_table(["指标", "值"], [
            ["样本 (8h)", f["n"]], ["最近一期 8h %", f["last_8h_pct"]], ["当前预测 8h %", f["current_predicted_8h_pct"]],
            ["年化 7 日 %", f["ann_7d_pct"]], ["年化 30 日 %", f["ann_30d_pct"]], ["年化 90 日 %", f["ann_90d_pct"]],
            ["年化 全样本 %", f["ann_all_pct"]], ["负费率占比", f["negative_share"]], ["最差单期 8h %", f["worst_8h_pct"]],
            ["30 日 carry 扣费后 (持有 90 天) %", f["net_30d_carry_pct_90d_hold"]]]),
        "", "### 交割合约基差 (Binance / Deribit)",
        md_table(["场所", "合约", "剩余天", "基差 %", "年化 %", "扣费年化 %"],
                 [[d["venue"], d["symbol"], d["days"], d["basis_pct"], d["ann_basis_pct"], d["net_ann_pct"]] for d in res["dated"]])])


if __name__ == "__main__":
    print(to_markdown(run(sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT")))
