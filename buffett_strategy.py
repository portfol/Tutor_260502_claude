"""
버핏 전략 핵심 로직.

Readme.txt 기반 8원칙:
  1) 이해의 영역 (산업 화이트리스트)
  2) 경쟁우위 (정성: GPT 평가)
  3) 사업의 체력: 일관된 이익 / ROE 12%+ / 부채 / FCF
  4) 안전마진: 내재가치 대비 20~30%+ 할인
  5) 오너 마인드 (정성)
  6) 장기 복리 (낮은 회전율)
  7) 단순함·절제 (레버리지 금지, 한 종목 비중 제한)
  8) 두 가지 규칙 (돈을 잃지 마라)

이 모듈은 정량 평가 + 내재가치 계산을 담당하고,
정성 평가(경쟁우위, 30초 설명, 경영진)는 gpt_analyst.py 가 담당합니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ---------------- 데이터 모델 ----------------

@dataclass
class Fundamentals:
    """종목 펀더멘털 (10년치 권장).

    값들은 연도별 시계열 (오래된 → 최신).
    재무 수치는 **억원** 단위로 입력하는 것을 표준으로 합니다.
    `financial_unit_won` 으로 환산 배수 변경 가능 (기본 1억원=1e8원).
    """
    ticker: str
    name: str
    industry: str
    revenue: list[float]                # 매출액 (억원)
    operating_income: list[float]       # 영업이익 (억원)
    net_income: list[float]             # 순이익 (억원)
    fcf: list[float]                    # 잉여현금흐름 (억원)
    roe: list[float]                    # ROE (%)
    debt_to_equity: list[float]         # 부채비율 (%)
    interest_coverage: list[float]      # 이자보상배율
    shares_outstanding: float           # 현재 발행주식수 (주)
    # 오너이익 추정용 (억원)
    depreciation: list[float] = field(default_factory=list)
    maintenance_capex: list[float] = field(default_factory=list)
    # 재무 단위 → 원 환산 (1억원 = 1e8원). 백만원 단위면 1e6 으로 변경.
    financial_unit_won: float = 1e8


@dataclass
class ScreeningResult:
    passed: bool
    score: float                        # 0.0 ~ 1.0
    checks: dict[str, bool]
    notes: list[str]


@dataclass
class IntrinsicValue:
    pessimistic: float                  # 비관 시나리오
    base: float                         # 기준
    optimistic: float                   # 낙관
    weighted: float                     # 비관 가중 평균
    per_share: float                    # 1주당 가중 내재가치


@dataclass
class BuffettSignal:
    ticker: str
    action: Literal["BUY", "HOLD", "SELL", "WATCH", "SKIP"]
    intrinsic_per_share: float
    target_buy_price: float              # 안전마진 적용된 목표 매수가
    current_price: float
    margin_of_safety_pct: float          # 현재가 기준 할인률
    screen: ScreeningResult
    reasons: list[str]


# ---------------- 1차 스크리닝 ----------------

def _trend_up(series: list[float], min_years: int = 5) -> bool:
    """우상향 추세인지 (선형 회귀 기울기 > 0 + 양수 비율 70% 이상)."""
    s = [x for x in series if x is not None]
    if len(s) < min_years:
        return False
    n = len(s)
    avg_x = (n - 1) / 2
    avg_y = sum(s) / n
    num = sum((i - avg_x) * (y - avg_y) for i, y in enumerate(s))
    den = sum((i - avg_x) ** 2 for i in range(n))
    if den == 0:
        return False
    slope = num / den
    pos_ratio = sum(1 for y in s if y > 0) / n
    return slope > 0 and pos_ratio >= 0.7


def screen_company(f: Fundamentals, industry_whitelist: list[str] | None = None) -> ScreeningResult:
    """버핏식 정량 스크리닝."""
    checks: dict[str, bool] = {}
    notes: list[str] = []

    # 이해의 영역
    if industry_whitelist:
        in_circle = f.industry in industry_whitelist
        checks["circle_of_competence"] = in_circle
        if not in_circle:
            notes.append(f"이해의 영역 밖 산업: {f.industry}")

    # 매출/영업이익 우상향
    checks["revenue_trend"] = _trend_up(f.revenue)
    checks["op_income_trend"] = _trend_up(f.operating_income)

    # ROE 12%+ 지속 (최근 5년 평균)
    recent_roe = f.roe[-5:] if len(f.roe) >= 5 else f.roe
    avg_roe = sum(recent_roe) / len(recent_roe) if recent_roe else 0
    checks["roe_12plus"] = avg_roe >= 12.0
    notes.append(f"평균 ROE(최근 5년): {avg_roe:.1f}%")

    # 부채 적정 (부채비율 200% 미만)
    recent_de = f.debt_to_equity[-3:] if f.debt_to_equity else [999]
    avg_de = sum(recent_de) / len(recent_de)
    checks["debt_ok"] = avg_de < 200.0
    notes.append(f"평균 부채비율(최근 3년): {avg_de:.0f}%")

    # 이자보상배율 양호 (5배 이상)
    recent_ic = f.interest_coverage[-3:] if f.interest_coverage else [0]
    avg_ic = sum(recent_ic) / len(recent_ic)
    checks["interest_coverage_ok"] = avg_ic >= 5.0

    # FCF 안정적 플러스 (최근 5년 중 4년 이상 +)
    recent_fcf = f.fcf[-5:] if len(f.fcf) >= 5 else f.fcf
    pos_fcf_years = sum(1 for x in recent_fcf if x > 0)
    checks["fcf_stable_positive"] = pos_fcf_years >= max(4, len(recent_fcf) - 1)

    passed_count = sum(1 for v in checks.values() if v)
    total = len(checks)
    score = passed_count / total if total else 0.0
    # 핵심 6개 중 5개 이상 통과해야 합격
    passed = passed_count >= max(5, total - 1)

    return ScreeningResult(passed=passed, score=score, checks=checks, notes=notes)


# ---------------- 내재가치 (Owner Earnings DCF) ----------------

def _owner_earnings(f: Fundamentals) -> float:
    """오너이익 = 세후이익 + 감가상각 - 유지보수성 CAPEX (최근 3년 평균, 보수적)."""
    n = min(3, len(f.net_income))
    if n == 0:
        return 0.0
    ni = sum(f.net_income[-n:]) / n
    dep = sum(f.depreciation[-n:]) / n if f.depreciation else 0.0
    capex = sum(f.maintenance_capex[-n:]) / n if f.maintenance_capex else 0.0
    if not f.depreciation and not f.maintenance_capex:
        # 데이터 없으면 FCF로 대체
        if f.fcf:
            m = min(3, len(f.fcf))
            return sum(f.fcf[-m:]) / m
    return ni + dep - capex


def intrinsic_value(
    f: Fundamentals,
    discount_rate: float = 0.10,
    horizon_years: int = 10,
) -> IntrinsicValue:
    """3-시나리오 DCF (비관/기준/낙관) 후 비관에 가중 평균."""
    oe = _owner_earnings(f)
    if oe <= 0:
        return IntrinsicValue(0, 0, 0, 0, 0)

    # 시나리오별 5년 성장률, 이후 0%
    scenarios = {
        "pessimistic": 0.02,
        "base": 0.05,
        "optimistic": 0.08,
    }
    values: dict[str, float] = {}
    for name, g in scenarios.items():
        pv = 0.0
        cf = oe
        for year in range(1, 6):
            cf *= 1 + g
            pv += cf / ((1 + discount_rate) ** year)
        # 이후 5년은 0% 성장 (보수적)
        for year in range(6, horizon_years + 1):
            pv += cf / ((1 + discount_rate) ** year)
        # 잔존가치는 매우 보수적: 마지막 CF / discount_rate * 0.5 의 PV
        terminal = (cf / discount_rate) * 0.5
        pv += terminal / ((1 + discount_rate) ** horizon_years)
        values[name] = pv

    weighted = (
        values["pessimistic"] * 0.5
        + values["base"] * 0.3
        + values["optimistic"] * 0.2
    )
    # 재무는 억원 등 단위, 주식수는 주 단위 → 원 단위 1주당 가치로 환산
    per_share = (
        (weighted * f.financial_unit_won) / f.shares_outstanding
        if f.shares_outstanding > 0 else 0
    )
    return IntrinsicValue(
        pessimistic=values["pessimistic"],
        base=values["base"],
        optimistic=values["optimistic"],
        weighted=weighted,
        per_share=per_share,
    )


# ---------------- 신호 생성 ----------------

def generate_signal(
    f: Fundamentals,
    current_price: float,
    margin_of_safety: float = 0.25,
    industry_whitelist: list[str] | None = None,
    held: bool = False,
    avg_buy_price: float | None = None,
) -> BuffettSignal:
    """버핏 원칙에 따라 BUY/HOLD/SELL/WATCH/SKIP 신호 생성."""
    screen = screen_company(f, industry_whitelist)
    iv = intrinsic_value(f)
    target_buy = iv.per_share * (1 - margin_of_safety)
    discount = (iv.per_share - current_price) / iv.per_share if iv.per_share > 0 else 0

    reasons: list[str] = []
    reasons.extend(screen.notes)
    reasons.append(f"내재가치(가중) per share: {iv.per_share:,.0f}원")
    reasons.append(f"안전마진 목표가: {target_buy:,.0f}원 (현재가 {current_price:,.0f})")

    # 매도 트리거 (보유 중인 경우)
    if held:
        # 1. 펀더멘털 붕괴
        if not screen.passed:
            return BuffettSignal(
                ticker=f.ticker, action="SELL",
                intrinsic_per_share=iv.per_share,
                target_buy_price=target_buy,
                current_price=current_price,
                margin_of_safety_pct=discount,
                screen=screen,
                reasons=reasons + ["펀더멘털 약화 → 매도"],
            )
        # 2. 고평가 (현재가 > 내재가치 * 1.3)
        if iv.per_share > 0 and current_price > iv.per_share * 1.3:
            return BuffettSignal(
                ticker=f.ticker, action="SELL",
                intrinsic_per_share=iv.per_share,
                target_buy_price=target_buy,
                current_price=current_price,
                margin_of_safety_pct=discount,
                screen=screen,
                reasons=reasons + ["고평가(내재가치 대비 30%+ 프리미엄) → 매도"],
            )
        return BuffettSignal(
            ticker=f.ticker, action="HOLD",
            intrinsic_per_share=iv.per_share,
            target_buy_price=target_buy,
            current_price=current_price,
            margin_of_safety_pct=discount,
            screen=screen, reasons=reasons + ["보유 유지"],
        )

    # 신규 매수 후보
    if current_price <= 0:
        return BuffettSignal(
            ticker=f.ticker, action="SKIP",
            intrinsic_per_share=iv.per_share,
            target_buy_price=target_buy,
            current_price=current_price,
            margin_of_safety_pct=0,
            screen=screen,
            reasons=reasons + ["현재가 미확인 - 시세 조회 실패"],
        )
    if not screen.passed:
        return BuffettSignal(
            ticker=f.ticker, action="SKIP",
            intrinsic_per_share=iv.per_share,
            target_buy_price=target_buy,
            current_price=current_price,
            margin_of_safety_pct=discount,
            screen=screen,
            reasons=reasons + ["스크리닝 미통과"],
        )

    if iv.per_share <= 0:
        return BuffettSignal(
            ticker=f.ticker, action="SKIP",
            intrinsic_per_share=0,
            target_buy_price=0,
            current_price=current_price,
            margin_of_safety_pct=0,
            screen=screen,
            reasons=reasons + ["내재가치 계산 불가(오너이익 음수)"],
        )

    if current_price <= target_buy:
        return BuffettSignal(
            ticker=f.ticker, action="BUY",
            intrinsic_per_share=iv.per_share,
            target_buy_price=target_buy,
            current_price=current_price,
            margin_of_safety_pct=discount,
            screen=screen,
            reasons=reasons + [f"안전마진 확보 (할인률 {discount*100:.1f}%) → 매수"],
        )

    return BuffettSignal(
        ticker=f.ticker, action="WATCH",
        intrinsic_per_share=iv.per_share,
        target_buy_price=target_buy,
        current_price=current_price,
        margin_of_safety_pct=discount,
        screen=screen,
        reasons=reasons + ["가격 미도달, 관찰리스트 유지"],
    )
