"""
백테스팅 엔진.

버핏식 백테스트의 본질:
- 매일 가격을 보지 않습니다 (장기 보유 가정).
- 안전마진 가격에 도달했을 때 분할 매수, 매도 트리거가 발동하면 매도.
- 회전율을 낮추고 시간(복리)에 베팅.

이 엔진은 단순화된 가정으로 작동합니다:
- 펀더멘털은 백테스트 시작 시점의 값 1세트 (point-in-time 데이터를 못 구할 때).
  더 정확한 백테스트를 원하면 연도별 펀더멘털 시계열로 확장 필요.
- 매수: 가격이 target_buy_price 이하일 때, 자본의 (1/split) 만큼 매수
- 매도: 가격이 내재가치 * 1.3 이상으로 올라가면 전량 매도
- 손실컷: 매수가 대비 -50% 이하로 빠지면 전량 매도 (펀더멘털 붕괴 가정)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from buffett_strategy import Fundamentals, generate_signal, intrinsic_value


@dataclass
class Trade:
    date: str
    action: str   # "BUY" / "SELL"
    price: float
    qty: int
    reason: str


@dataclass
class BacktestResult:
    ticker: str
    initial_cash: float
    final_value: float
    total_return_pct: float
    cagr_pct: float
    num_trades: int
    max_drawdown_pct: float
    avg_buy_price: float
    holding_days: int
    trades: list[Trade]
    equity_curve: list[dict[str, Any]]   # [{date, equity}, ...]
    intrinsic_per_share: float
    target_buy_price: float


def _years_between(start: str, end: str) -> float:
    # YYYYMMDD
    from datetime import datetime
    s = datetime.strptime(start, "%Y%m%d")
    e = datetime.strptime(end, "%Y%m%d")
    return max((e - s).days / 365.25, 1e-9)


def run_backtest(
    f: Fundamentals,
    price_history: list[dict[str, Any]],   # [{date(YYYYMMDD), open, high, low, close, volume}, ...] 최신→과거
    initial_cash: float = 10_000_000,       # 1천만원
    margin_of_safety: float = 0.25,
    split_buy_count: int = 3,
    sell_premium: float = 0.30,             # 내재가치 +30% 이상이면 매도
    stop_loss: float = 0.50,                # 평단 대비 -50% 이상이면 손절
) -> BacktestResult:
    if not price_history:
        raise ValueError("price_history 가 비어있습니다.")

    # 과거→최신 순으로 정렬
    history = sorted(price_history, key=lambda x: x["date"])
    if not history:
        raise ValueError("price_history 정렬 후 비어있습니다.")

    iv = intrinsic_value(f)
    target_buy = iv.per_share * (1 - margin_of_safety)
    sell_threshold = iv.per_share * (1 + sell_premium)

    cash = float(initial_cash)
    qty = 0
    avg_buy_price = 0.0
    buys_done = 0
    cash_per_split = initial_cash / split_buy_count

    trades: list[Trade] = []
    equity_curve: list[dict[str, Any]] = []
    peak_equity = initial_cash
    max_dd = 0.0
    first_buy_date: str | None = None
    last_date: str = history[-1]["date"]

    for row in history:
        price = row["close"]
        date = row["date"]

        # 매수 로직: 안전마진 충족 + 분할매수 잔량 있음
        if (
            iv.per_share > 0
            and price > 0
            and price <= target_buy
            and buys_done < split_buy_count
            and cash >= cash_per_split * 0.99
        ):
            buy_amount = min(cash_per_split, cash)
            buy_qty = int(buy_amount // price)
            if buy_qty > 0:
                cost = buy_qty * price
                new_qty = qty + buy_qty
                avg_buy_price = (avg_buy_price * qty + cost) / new_qty if new_qty else 0
                qty = new_qty
                cash -= cost
                buys_done += 1
                if first_buy_date is None:
                    first_buy_date = date
                trades.append(Trade(
                    date=date, action="BUY", price=price, qty=buy_qty,
                    reason=f"안전마진 가격 도달 ({buys_done}/{split_buy_count} 차)"
                ))

        # 매도 로직
        if qty > 0:
            sell_reason = None
            if iv.per_share > 0 and price >= sell_threshold:
                sell_reason = f"고평가 (내재가치 +{sell_premium*100:.0f}% 도달) → 전량 매도"
            elif avg_buy_price > 0 and price <= avg_buy_price * (1 - stop_loss):
                sell_reason = f"손실컷 (-{stop_loss*100:.0f}%) → 전량 매도"
            if sell_reason:
                proceeds = qty * price
                cash += proceeds
                trades.append(Trade(
                    date=date, action="SELL", price=price, qty=qty, reason=sell_reason,
                ))
                qty = 0
                avg_buy_price = 0.0
                buys_done = 0  # 재진입 가능

        equity = cash + qty * price
        equity_curve.append({"date": date, "equity": round(equity, 2), "price": price})
        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
        if dd > max_dd:
            max_dd = dd

    final_price = history[-1]["close"]
    final_value = cash + qty * final_price
    total_return = (final_value / initial_cash - 1) * 100

    years = _years_between(history[0]["date"], history[-1]["date"])
    cagr = ((final_value / initial_cash) ** (1 / years) - 1) * 100 if final_value > 0 else -100.0

    holding_days = 0
    if first_buy_date:
        from datetime import datetime
        holding_days = (datetime.strptime(last_date, "%Y%m%d") - datetime.strptime(first_buy_date, "%Y%m%d")).days

    return BacktestResult(
        ticker=f.ticker,
        initial_cash=initial_cash,
        final_value=round(final_value, 2),
        total_return_pct=round(total_return, 2),
        cagr_pct=round(cagr, 2),
        num_trades=len(trades),
        max_drawdown_pct=round(max_dd * 100, 2),
        avg_buy_price=round(avg_buy_price, 2),
        holding_days=holding_days,
        trades=trades,
        equity_curve=equity_curve,
        intrinsic_per_share=round(iv.per_share, 2),
        target_buy_price=round(target_buy, 2),
    )
