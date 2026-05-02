"""
주가 클라이언트 (pykrx 기반).

pykrx 는 한국거래소(KRX) 데이터를 스크래핑합니다 — 무료, 인증 불필요.

기능:
  - 일봉 OHLCV 조회 (최근 N일)
  - 현재가 (가장 최근 영업일 종가)
  - 종목명 조회
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from pykrx import stock


def _normalize_columns(df) -> list[dict[str, Any]]:
    """pykrx DataFrame → backtest 엔진이 쓰는 dict 리스트 (최신→과거)."""
    rows: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        # 한글 컬럼명 위치 기반 접근 (시가, 고가, 저가, 종가, 거래량, 등락률)
        cols = list(df.columns)
        date = idx.strftime("%Y%m%d") if hasattr(idx, "strftime") else str(idx)
        try:
            rows.append({
                "date": date,
                "open": float(row.iloc[0]),
                "high": float(row.iloc[1]),
                "low": float(row.iloc[2]),
                "close": float(row.iloc[3]),
                "volume": float(row.iloc[4]),
            })
        except (IndexError, ValueError, TypeError):
            continue
    rows.reverse()  # 최신 → 과거
    return rows


def _fetch_ohlcv_sync(ticker: str, days: int) -> list[dict[str, Any]]:
    end = datetime.now()
    start = end - timedelta(days=int(days * 1.6) + 30)  # 영업일 보정 + 여유
    df = stock.get_market_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker)
    if df is None or df.empty:
        return []
    rows = _normalize_columns(df)
    return rows[:days]


async def get_daily_chart(ticker: str, days: int = 1000) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_fetch_ohlcv_sync, ticker, days)


async def get_current_price(ticker: str) -> float | None:
    rows = await get_daily_chart(ticker, days=5)
    if not rows:
        return None
    return rows[0]["close"]


def _get_name_sync(ticker: str) -> str:
    try:
        return stock.get_market_ticker_name(ticker) or ""
    except Exception:
        return ""


async def get_name(ticker: str) -> str:
    return await asyncio.to_thread(_get_name_sync, ticker)
