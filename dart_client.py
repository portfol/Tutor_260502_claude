"""
DART OpenAPI 클라이언트.

전자공시시스템 (https://opendart.fss.or.kr) 에서 한국 상장사 재무제표를 가져옵니다.

흐름:
  1. 종목코드 → corp_code 매핑 (corpCode.xml zip 1회 다운로드 후 캐시)
  2. 사업보고서(연간)에서 단일회사 전체 재무제표 조회 (fnlttSinglAcntAll)
  3. 발행주식수 조회 (stockTotqySttus)
  4. 10년치 누적 → Fundamentals 객체로 변환

API 한도: 일 10,000건 (10년치 = 종목당 ~12콜).
"""
from __future__ import annotations

import io
import json
import logging
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from typing import Any

import httpx

from buffett_strategy import Fundamentals
from config import get_runtime_data_dir, settings

log = logging.getLogger("dart")

_BASE = "https://opendart.fss.or.kr/api"
_DATA_DIR = get_runtime_data_dir()
_CORP_CACHE = _DATA_DIR / "corp_code_map.json"


# ---------------- corp_code 매핑 ----------------

async def _download_corp_code_map() -> dict[str, dict[str, str]]:
    """corpCode.xml zip 다운로드 → {stock_code: {corp_code, corp_name}} 매핑."""
    if not settings.dart_api_key:
        raise RuntimeError("DART_API_KEY 가 설정되지 않았습니다 (.env 확인)")

    url = f"{_BASE}/corpCode.xml?crtfc_key={settings.dart_api_key}"
    async with httpx.AsyncClient(timeout=60.0) as cli:
        r = await cli.get(url)
        r.raise_for_status()

    # 응답이 zip 인지 JSON 에러인지 확인
    if r.headers.get("content-type", "").startswith("application/json"):
        raise RuntimeError(f"DART corp_code 조회 실패: {r.text}")

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        with z.open(z.namelist()[0]) as fp:
            xml_bytes = fp.read()

    root = ET.fromstring(xml_bytes)
    mapping: dict[str, dict[str, str]] = {}
    for item in root.findall("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        corp_code = (item.findtext("corp_code") or "").strip()
        corp_name = (item.findtext("corp_name") or "").strip()
        if stock_code and len(stock_code) == 6:  # 상장사만
            mapping[stock_code] = {"corp_code": corp_code, "corp_name": corp_name}

    with _CORP_CACHE.open("w", encoding="utf-8") as fp:
        json.dump({"updated": datetime.now().isoformat(), "map": mapping}, fp, ensure_ascii=False)
    log.info(f"corp_code 매핑 캐시 저장 ({len(mapping)} 종목)")
    return mapping


async def _get_corp_code_map() -> dict[str, dict[str, str]]:
    if _CORP_CACHE.exists():
        with _CORP_CACHE.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        return data.get("map", {})
    return await _download_corp_code_map()


async def search_companies(query: str, limit: int = 15) -> list[dict[str, str]]:
    """회사명으로 부분일치 검색. 정확일치 → 접두일치 → 포함 순으로 정렬."""
    q = (query or "").strip().lower()
    if not q:
        return []
    try:
        mp = await _get_corp_code_map()
    except RuntimeError as e:
        raise RuntimeError(f"{e} Vercel 환경변수에 DART_API_KEY를 등록한 뒤 재배포하세요.") from e

    exact: list[dict[str, str]] = []
    prefix: list[dict[str, str]] = []
    contains: list[dict[str, str]] = []
    for stock_code, info in mp.items():
        name = info["corp_name"]
        nl = name.lower()
        # 티커가 정확히 일치하는 경우
        if stock_code == query.strip():
            exact.insert(0, {"ticker": stock_code, "name": name})
            continue
        if nl == q:
            exact.append({"ticker": stock_code, "name": name})
        elif nl.startswith(q):
            prefix.append({"ticker": stock_code, "name": name})
        elif q in nl:
            contains.append({"ticker": stock_code, "name": name})

    return (exact + prefix + contains)[:limit]


async def lookup_corp(ticker: str) -> dict[str, str]:
    """6자리 종목코드 → {corp_code, corp_name}."""
    ticker = ticker.zfill(6)
    mp = await _get_corp_code_map()
    if ticker not in mp:
        # 캐시 미스 - 재다운로드 시도
        mp = await _download_corp_code_map()
    if ticker not in mp:
        raise KeyError(f"DART 에서 종목코드 {ticker} 를 찾을 수 없습니다.")
    return mp[ticker]


# ---------------- 재무제표 조회 ----------------

# DART 계정명 매핑 (회사마다 표기 다름 → 후보들)
_ACCOUNT_KEYS = {
    "revenue": ["매출액", "수익(매출액)", "영업수익", "매출"],
    "operating_income": ["영업이익", "영업이익(손실)"],
    "net_income": ["당기순이익", "당기순이익(손실)", "분기순이익", "반기순이익"],
    "total_equity": ["자본총계"],
    "total_debt": ["부채총계"],
    "interest_expense": ["이자비용"],
    "operating_cf": ["영업활동현금흐름", "영업활동으로 인한 현금흐름", "영업활동으로인한현금흐름"],
    "investing_cf": ["투자활동현금흐름", "투자활동으로 인한 현금흐름", "투자활동으로인한현금흐름"],
    "depreciation": ["감가상각비"],
}


def _parse_amount(s: str | None) -> float:
    if not s:
        return 0.0
    try:
        return float(str(s).replace(",", "").replace(" ", ""))
    except (ValueError, TypeError):
        return 0.0


def _extract(rows: list[dict[str, Any]], candidates: list[str]) -> float:
    """rows 에서 account_nm 이 candidates 중 하나와 일치하는 항목의 thstrm_amount 합."""
    for cand in candidates:
        for row in rows:
            nm = (row.get("account_nm") or "").strip()
            if nm == cand:
                return _parse_amount(row.get("thstrm_amount"))
    # 부분 매칭 폴백
    for cand in candidates:
        for row in rows:
            nm = (row.get("account_nm") or "").strip()
            if cand in nm:
                return _parse_amount(row.get("thstrm_amount"))
    return 0.0


async def _fetch_yearly_financials(corp_code: str, year: int) -> dict[str, float] | None:
    """단일 사업보고서 (연결 우선, 실패 시 별도)."""
    for fs_div in ("CFS", "OFS"):  # 연결 → 별도
        params = {
            "crtfc_key": settings.dart_api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": "11011",  # 사업보고서
            "fs_div": fs_div,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as cli:
                r = await cli.get(f"{_BASE}/fnlttSinglAcntAll.json", params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            log.warning(f"[{corp_code} {year} {fs_div}] 재무 조회 오류: {e}")
            continue

        if data.get("status") != "000":
            continue
        rows = data.get("list", []) or []
        if not rows:
            continue

        return {
            "revenue": _extract(rows, _ACCOUNT_KEYS["revenue"]),
            "operating_income": _extract(rows, _ACCOUNT_KEYS["operating_income"]),
            "net_income": _extract(rows, _ACCOUNT_KEYS["net_income"]),
            "total_equity": _extract(rows, _ACCOUNT_KEYS["total_equity"]),
            "total_debt": _extract(rows, _ACCOUNT_KEYS["total_debt"]),
            "interest_expense": _extract(rows, _ACCOUNT_KEYS["interest_expense"]),
            "operating_cf": _extract(rows, _ACCOUNT_KEYS["operating_cf"]),
            "investing_cf": _extract(rows, _ACCOUNT_KEYS["investing_cf"]),
            "depreciation": _extract(rows, _ACCOUNT_KEYS["depreciation"]),
        }
    return None


async def _fetch_shares_outstanding(corp_code: str, year: int) -> float:
    """주식총수 조회 (보통주 발행주식 총수)."""
    params = {
        "crtfc_key": settings.dart_api_key,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": "11011",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.get(f"{_BASE}/stockTotqySttus.json", params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning(f"[{corp_code}] 주식총수 조회 오류: {e}")
        return 0.0

    if data.get("status") != "000":
        return 0.0
    for row in data.get("list", []) or []:
        # 보통주
        if "보통주" in (row.get("se") or ""):
            issued = _parse_amount(row.get("istc_totqy"))
            treasury = _parse_amount(row.get("tesstk_co"))
            return max(issued - treasury, issued)
    return 0.0


# ---------------- 통합: Fundamentals 빌드 ----------------

async def build_fundamentals(
    ticker: str,
    industry: str = "",
    years: int = 10,
) -> Fundamentals:
    """종목코드 입력 → 10년치 사업보고서 + 주식수 → Fundamentals."""
    info = await lookup_corp(ticker)
    corp_code = info["corp_code"]
    corp_name = info["corp_name"]

    # 가장 최근 보고서가 나와 있는 해부터 거꾸로 (보통 작년치까지 가능)
    end_year = datetime.now().year - 1
    start_year = end_year - years + 1

    rev: list[float] = []
    opi: list[float] = []
    ni: list[float] = []
    fcf: list[float] = []
    roe: list[float] = []
    de: list[float] = []
    ic: list[float] = []
    dep: list[float] = []
    capex: list[float] = []

    for year in range(start_year, end_year + 1):
        fs = await _fetch_yearly_financials(corp_code, year)
        if not fs:
            log.info(f"[{ticker} {year}] 재무 없음 - 스킵")
            continue

        rev.append(fs["revenue"])
        opi.append(fs["operating_income"])
        ni.append(fs["net_income"])
        # FCF ≈ 영업CF + 투자CF (투자CF는 음수)
        fcf.append(fs["operating_cf"] + fs["investing_cf"])
        # ROE = 순이익 / 자본총계 * 100
        roe.append((fs["net_income"] / fs["total_equity"] * 100) if fs["total_equity"] else 0.0)
        # 부채비율
        de.append((fs["total_debt"] / fs["total_equity"] * 100) if fs["total_equity"] else 0.0)
        # 이자보상배율
        ic.append((fs["operating_income"] / fs["interest_expense"]) if fs["interest_expense"] else 999.0)
        dep.append(fs["depreciation"])
        # 유지보수성 CAPEX 근사 = 감가상각비 (보수적 가정)
        capex.append(fs["depreciation"])

    if not rev:
        raise RuntimeError(f"{ticker}: 최근 {years}년간 사업보고서 데이터를 가져오지 못했습니다.")

    shares = await _fetch_shares_outstanding(corp_code, end_year)
    if shares <= 0:
        # 직전 연도 시도
        shares = await _fetch_shares_outstanding(corp_code, end_year - 1)

    return Fundamentals(
        ticker=ticker,
        name=corp_name,
        industry=industry or "미분류",
        revenue=rev,
        operating_income=opi,
        net_income=ni,
        fcf=fcf,
        roe=roe,
        debt_to_equity=de,
        interest_coverage=ic,
        shares_outstanding=shares,
        depreciation=dep,
        maintenance_capex=capex,
        # DART 응답은 원 단위
        financial_unit_won=1.0,
    )
