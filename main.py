"""
FastAPI 메인 앱 — 분석 + 백테스트 전용.

데이터:
  - 펀더멘털: DART OpenAPI (재무제표)
  - 주가: pykrx (KRX 일봉)
  - 정성 평가: OpenAI GPT

페이지:
  GET /                  - 웹 대시보드

API:
  GET  /api/fetch-fundamentals/{ticker}  - DART 자동조회
  GET  /api/watchlist                    - 목록 조회
  POST /api/watchlist                    - 등록/갱신
  DELETE /api/watchlist/{ticker}         - 삭제

  POST /api/analyze/{ticker}             - 정량 + GPT 정성 분석
  POST /api/backtest/{ticker}            - 백테스트 (pykrx 일봉)
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

import dart_client
import price_client
import watchlist_store
from backtest_engine import run_backtest
from buffett_strategy import Fundamentals, generate_signal
from config import settings
from gpt_analyst import analyze_qualitative


app = FastAPI(title="버핏 봇 - DART + pykrx 분석/백테스트")
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ---------------- Pydantic ----------------

class FundamentalsIn(BaseModel):
    ticker: str
    name: str
    industry: str
    revenue: list[float]
    operating_income: list[float]
    net_income: list[float]
    fcf: list[float]
    roe: list[float]
    debt_to_equity: list[float]
    interest_coverage: list[float]
    shares_outstanding: float
    depreciation: list[float] = Field(default_factory=list)
    maintenance_capex: list[float] = Field(default_factory=list)
    financial_unit_won: float = 1e8


class WatchlistEntryIn(BaseModel):
    fundamentals: FundamentalsIn
    memo: str = ""


class BacktestIn(BaseModel):
    initial_cash: float = 10_000_000
    days: int = 1000
    margin_of_safety: float | None = None
    split_buy_count: int | None = None


# ---------------- 페이지 ----------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "margin_of_safety": settings.margin_of_safety,
        },
    )


# ---------------- DART 자동조회 ----------------

@app.get("/api/search-companies")
async def api_search_companies(q: str = "", limit: int = 15):
    """회사명 자동완성 (DART corp_code 캐시 기반)."""
    try:
        return await dart_client.search_companies(q, limit=limit)
    except Exception as e:
        raise HTTPException(502, str(e))


@app.get("/api/fetch-fundamentals/{ticker}")
async def api_fetch_fundamentals(ticker: str, industry: str = "", years: int = 10):
    try:
        f = await dart_client.build_fundamentals(ticker, industry=industry, years=years)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    except Exception as e:
        raise HTTPException(502, f"DART 조회 실패: {e}")
    return {
        "ticker": f.ticker,
        "name": f.name,
        "industry": f.industry,
        "shares_outstanding": f.shares_outstanding,
        "revenue": f.revenue,
        "operating_income": f.operating_income,
        "net_income": f.net_income,
        "fcf": f.fcf,
        "roe": [round(x, 2) for x in f.roe],
        "debt_to_equity": [round(x, 2) for x in f.debt_to_equity],
        "interest_coverage": [round(x, 2) for x in f.interest_coverage],
        "depreciation": f.depreciation,
        "maintenance_capex": f.maintenance_capex,
        "financial_unit_won": f.financial_unit_won,
    }


# ---------------- Watchlist ----------------

@app.get("/api/watchlist")
async def api_watchlist_list():
    return watchlist_store.list_watchlist()


@app.post("/api/watchlist")
async def api_watchlist_upsert(entry: WatchlistEntryIn):
    f = Fundamentals(**entry.fundamentals.model_dump())
    saved = watchlist_store.upsert_entry(f, memo=entry.memo)
    return saved


@app.delete("/api/watchlist/{ticker}")
async def api_watchlist_delete(ticker: str):
    if not watchlist_store.remove_entry(ticker):
        raise HTTPException(404, "종목을 찾을 수 없습니다.")
    return {"ok": True}


# ---------------- 분석 ----------------

@app.post("/api/analyze/{ticker}")
async def api_analyze(ticker: str, use_gpt: bool = True) -> dict[str, Any]:
    entry = watchlist_store.get_entry(ticker)
    if not entry:
        raise HTTPException(404, "관찰리스트에 없는 종목입니다. 먼저 등록하세요.")

    f = Fundamentals(**entry["fundamentals"])

    current_price = await price_client.get_current_price(ticker) or 0.0
    sig = generate_signal(
        f, current_price=current_price,
        margin_of_safety=settings.margin_of_safety,
    )

    result: dict[str, Any] = {
        "ticker": ticker,
        "current_price": current_price,
        "signal": {
            "action": sig.action,
            "intrinsic_per_share": sig.intrinsic_per_share,
            "target_buy_price": sig.target_buy_price,
            "margin_of_safety_pct": sig.margin_of_safety_pct,
            "screen": {
                "passed": sig.screen.passed,
                "score": sig.screen.score,
                "checks": sig.screen.checks,
                "notes": sig.screen.notes,
            },
            "reasons": sig.reasons,
        },
    }

    if use_gpt:
        try:
            qual = await analyze_qualitative(f, sig)
            result["gpt"] = {
                "moat_score": qual.moat_score,
                "moat_reason": qual.moat_reason,
                "management_score": qual.management_score,
                "management_reason": qual.management_reason,
                "thirty_second_pitch": qual.thirty_second_pitch,
                "risks": qual.risks,
                "final_verdict": qual.final_verdict,
                "final_reason": qual.final_reason,
            }
        except Exception as e:
            result["gpt_error"] = str(e)

    return result


# ---------------- 백테스트 ----------------

@app.post("/api/backtest/{ticker}")
async def api_backtest(ticker: str, body: BacktestIn):
    entry = watchlist_store.get_entry(ticker)
    if not entry:
        raise HTTPException(404, "관찰리스트에 없는 종목입니다. 먼저 등록하세요.")
    f = Fundamentals(**entry["fundamentals"])

    try:
        chart = await price_client.get_daily_chart(ticker, days=body.days)
    except Exception as e:
        raise HTTPException(502, f"가격 조회 실패 (pykrx): {e}")
    if not chart:
        raise HTTPException(404, "가격 데이터가 없습니다.")

    result = run_backtest(
        f, price_history=chart,
        initial_cash=body.initial_cash,
        margin_of_safety=body.margin_of_safety if body.margin_of_safety is not None else settings.margin_of_safety,
        split_buy_count=body.split_buy_count or settings.split_buy_count,
    )
    return {
        "ticker": result.ticker,
        "summary": {
            "initial_cash": result.initial_cash,
            "final_value": result.final_value,
            "total_return_pct": result.total_return_pct,
            "cagr_pct": result.cagr_pct,
            "max_drawdown_pct": result.max_drawdown_pct,
            "num_trades": result.num_trades,
            "holding_days": result.holding_days,
            "intrinsic_per_share": result.intrinsic_per_share,
            "target_buy_price": result.target_buy_price,
        },
        "trades": [asdict(t) for t in result.trades],
        "equity_curve": result.equity_curve,
    }


@app.get("/api/health")
async def api_health():
    return {
        "ok": True,
        "model": settings.openai_model,
        "data_sources": {"fundamentals": "DART", "prices": "pykrx (KRX)"},
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
