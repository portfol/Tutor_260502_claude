"""
GPT 기반 정성 평가.

버핏 체크리스트 중 정량으로 잡기 어려운 항목들을 GPT 가 평가:
- 경쟁우위(해자): 브랜드/네트워크/전환비용
- 경영진의 자본배분 능력
- 30초 설명 테스트
- 종합 매매 의견
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from openai import AsyncOpenAI

from buffett_strategy import BuffettSignal, Fundamentals
from config import settings


_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY 가 설정되지 않았습니다 (.env 확인)")
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


@dataclass
class QualitativeAnalysis:
    moat_score: int          # 0~10
    moat_reason: str
    management_score: int    # 0~10
    management_reason: str
    thirty_second_pitch: str
    risks: list[str]
    final_verdict: str       # "BUY" / "HOLD" / "SELL" / "SKIP"
    final_reason: str
    raw: str


SYSTEM_PROMPT = """당신은 워렌 버핏의 투자 원칙을 따르는 가치투자 분석가입니다.

평가 원칙:
1. 이해의 영역: 사업이 단순하고 이해 가능한가?
2. 경제적 해자: 브랜드/네트워크/전환비용/규모의 경제 중 무엇이 있는가?
3. 경영진: 정직성, 일관성, 자본배분 능력
4. 안전마진: 내재가치 대비 충분히 싼가?
5. 장기 보유: 10년 보유해도 좋을 회사인가?

출력은 반드시 아래 JSON 형식만으로 응답하세요. 다른 텍스트 금지.
{
  "moat_score": 0-10 정수,
  "moat_reason": "해자에 대한 한 문단 평가",
  "management_score": 0-10 정수,
  "management_reason": "경영진 평가",
  "thirty_second_pitch": "이 사업을 30초 안에 설명",
  "risks": ["핵심 위험 1", "핵심 위험 2", "핵심 위험 3"],
  "final_verdict": "BUY 또는 HOLD 또는 SELL 또는 SKIP",
  "final_reason": "최종 판단 근거 한 문단"
}
"""


async def analyze_qualitative(
    f: Fundamentals,
    signal: BuffettSignal,
    extra_context: str = "",
) -> QualitativeAnalysis:
    """정량 신호를 받아 GPT 가 정성 평가를 더해 최종 판단을 내립니다."""
    cli = _get_client()

    user_msg = f"""다음 종목을 버핏 원칙에 따라 평가하세요.

[기본정보]
- 티커: {f.ticker}
- 회사명: {f.name}
- 산업: {f.industry}

[정량 평가 결과]
- 스크리닝 통과: {signal.screen.passed}
- 통과 점수: {signal.screen.score:.2f}
- 체크 항목: {json.dumps(signal.screen.checks, ensure_ascii=False)}
- 메모: {signal.screen.notes}

[가치 평가]
- 내재가치(주당, 가중): {signal.intrinsic_per_share:,.0f}원
- 현재가: {signal.current_price:,.0f}원
- 안전마진 목표가: {signal.target_buy_price:,.0f}원
- 정량 시그널: {signal.action}

[재무 추세]
- 최근 5년 매출: {f.revenue[-5:] if len(f.revenue) >= 5 else f.revenue}
- 최근 5년 영업이익: {f.operating_income[-5:] if len(f.operating_income) >= 5 else f.operating_income}
- 최근 5년 ROE: {f.roe[-5:] if len(f.roe) >= 5 else f.roe}
- 최근 5년 FCF: {f.fcf[-5:] if len(f.fcf) >= 5 else f.fcf}

[추가 컨텍스트]
{extra_context or "(없음)"}

위 정보를 바탕으로 정성 평가를 더해 최종 매매 판단을 내리세요.
"""

    resp = await cli.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    raw = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}

    return QualitativeAnalysis(
        moat_score=int(data.get("moat_score", 0)),
        moat_reason=data.get("moat_reason", ""),
        management_score=int(data.get("management_score", 0)),
        management_reason=data.get("management_reason", ""),
        thirty_second_pitch=data.get("thirty_second_pitch", ""),
        risks=data.get("risks", []) or [],
        final_verdict=data.get("final_verdict", signal.action),
        final_reason=data.get("final_reason", ""),
        raw=raw,
    )
