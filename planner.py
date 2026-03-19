"""
planner.py — 고수준 계획 수립 + 동적 계획 리뷰
- create_plan: 초기 계획 수립 (1회)
- review_plan: 매 스텝 실행 후 결과를 보고 남은 계획 조정 (동적)
"""
import json
import re
from dataclasses import dataclass

import openai


@dataclass
class PlanStep:
    name: str          # 단계 이름 (예: "CPU 선택")
    budget: int        # 이 부품에 쓸 최대 예산 (원), 0이면 제한 없음
    hint: str          # 필터/규격 힌트 (선택) — 특정 모델명 아님


PLAN_SYSTEM = """\
당신은 PC 견적 웹 에이전트의 계획 수립자입니다.
주어진 예산과 목적을 분석해 필요한 부품을 결정하고 예산을 배분하세요.
실제 제품 탐색은 에이전트가 쇼핑몰을 직접 브라우징하므로,
특정 모델명이나 가격 시세표 없이 순수하게 추론하면 됩니다.

## 사고 방식
1. 이 PC가 어떤 용도인지 파악한다 (사무/게이밍/저예산 등)
2. 그 용도에 필요한 부품 구성을 결정한다
   - 사무용이면 GPU가 불필요하므로 CPU에 내장그래픽이 있어야 한다
   - 게이밍이면 GPU가 필수이므로 CPU는 내장그래픽 없는 저렴한 모델로
   - 예산이 아주 낮으면 최소 구성 (CPU+MB+RAM+SSD+케이스+파워)
3. 총 예산의 90% 이하로 부품 예산 합계를 맞춘다 (버퍼 10%)
4. 용도와 예산에 맞게 각 부품에 비중을 배분한다
   - 게이밍: GPU에 30~40%, CPU에 15~20%
   - 사무용: CPU(내장그래픽)에 20~25%, 나머지 균등 배분
5. hint는 검색/필터에 도움이 되는 규격 정보만 (모델명 아님)
   - 예: "내장그래픽 포함 필수", "DDR4", "NVMe M.2", "마이크로ATX"
   - 특정 모델명(예: Ryzen 5 5600G, i3-12100) 절대 금지
   - 단순한 부품이면 hint 비워도 됨

## 출력 형식
반드시 아래 JSON 형식만 출력하세요. 다른 텍스트, 설명, 마크다운 없이 JSON만:
{
  "steps": [
    {"name": "CPU 선택", "budget": 120000, "hint": "내장그래픽 포함 필수"},
    {"name": "메인보드 선택", "budget": 70000, "hint": ""},
    {"name": "최종 견적 확인 및 결과 정리", "budget": 0, "hint": ""}
  ]
}

## 주의
- 마지막 단계는 반드시 "최종 견적 확인 및 결과 정리" (budget=0, hint="")
- 단계 수: 4~7개
- 에이전트가 실제 쇼핑몰을 탐색하므로 hint가 없어도 저렴한 제품을 스스로 찾을 수 있음
"""


def _extract_steps(raw: str) -> list[PlanStep]:
    """
    LLM 응답에서 steps 리스트를 추출한다.
    Gemini 등이 JSON 앞뒤에 preamble을 붙이는 경우도 처리.
    """
    # 1. 코드 블록 제거
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    parsed_data = None

    # 2. 응답 전체가 JSON이면 바로 파싱
    try:
        parsed_data = json.loads(cleaned)
    except Exception:
        pass

    # 3. 응답 내에서 {"steps": [...]} 패턴 찾기 (preamble 있어도 처리)
    if parsed_data is None:
        m = re.search(r'\{[^{}]*"steps"\s*:\s*\[.*?\]\s*\}', cleaned, re.DOTALL)
        if m:
            try:
                parsed_data = json.loads(m.group(0))
            except Exception:
                pass

    # 4. 구조화 파싱 시도
    if parsed_data:
        raw_steps = parsed_data.get("steps", [])
        if raw_steps:
            result = []
            for s in raw_steps:
                if isinstance(s, dict):
                    result.append(PlanStep(
                        name=str(s.get("name", "")).strip(),
                        budget=int(s.get("budget", 0) or 0),
                        hint=str(s.get("hint", "")).strip(),
                    ))
                elif isinstance(s, str) and s.strip():
                    # 구형 포맷 fallback: 문자열만 있으면 budget=0, hint=""
                    result.append(PlanStep(name=s.strip(), budget=0, hint=""))
            if result:
                return result

    # 5. 마지막 fallback: 번호 붙은 줄 파싱 (1. ... / 2. ...)
    steps = []
    for line in cleaned.splitlines():
        line = re.sub(r'^\s*[\d]+[.)]\s*', "", line).strip()
        line = line.strip('",[]{} ')
        if len(line) > 5:
            steps.append(PlanStep(name=line, budget=0, hint=""))
    return steps or [PlanStep(name="태스크 전체를 한 번에 처리", budget=0, hint="")]


def create_plan(task: str, budget: int, client: openai.OpenAI, model: str) -> list[PlanStep]:
    """태스크를 예산 배분이 포함된 서브태스크 목록으로 분해한다."""
    user_msg = f"태스크: {task}\n총 예산: {budget:,}원"
    response = client.chat.completions.create(
        model=model,
        max_tokens=512,
        messages=[
            {"role": "system", "content": PLAN_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
    )
    raw = response.choices[0].message.content.strip()
    return _extract_steps(raw)


_REVIEW_SYSTEM = """\
당신은 PC 견적 웹 에이전트의 계획 관리자입니다.
에이전트가 한 단계를 실행한 후, 결과를 분석하고 남은 계획을 조정하세요.

## 역할
- 방금 실행된 단계의 결과(성공/실패, 실제 소요 예산)를 반영한다
- 남은 계획이 여전히 적절한지 판단한다
- 필요하면 남은 계획을 수정한다

## 조정 원칙
성공한 경우:
- 실제 지출 예산을 반영해 잔여 예산을 재계산한다
- 이미 선택된 부품과 호환되도록 다음 단계 hint를 조정한다 (예: CPU 소켓에 맞는 메인보드)

실패한 경우:
- 같은 방법을 반복하지 말 것 — 반드시 다른 접근법을 택한다
- 예산 내 제품이 없으면: 예산을 소폭 상향하거나, 다른 브랜드/소켓 시도
  - 인텔 소켓1700 + 내장그래픽 + 저예산 → AMD APU(Ryzen G) 또는 예산 상향
  - 특정 필터 실패 → 필터 없이 카테고리 탐색
- 실패 단계를 다시 계획에 포함시킬 때는 hint를 바꿔서 다른 전략을 명시한다

## 출력 형식
반드시 JSON만 출력 (다른 텍스트 없이):
{
  "reasoning": "조정 근거 한 줄",
  "steps": [
    {"name": "...", "budget": 0, "hint": ""}
  ]
}

주의:
- steps는 아직 완료되지 않은 남은 단계만 포함 (이미 완료된 단계 제외)
- 마지막 단계는 반드시 "최종 견적 확인 및 결과 정리" (budget=0, hint="")
- hint에 특정 모델명 금지 — 규격/전략 힌트만 허용
"""


def review_plan(
    task: str,
    budget: int,
    spent_so_far: int,
    completed: list[str],
    last_step_name: str,
    last_step_result: str,
    last_step_success: bool,
    remaining_steps: list["PlanStep"],
    client: openai.OpenAI,
    model: str,
) -> list["PlanStep"]:
    """
    매 스텝 실행 후 결과를 보고 남은 계획을 동적으로 조정한다.
    성공/실패 모두 호출 — 실제 지출과 관찰 결과를 반영한다.
    """
    remaining_budget = budget - spent_so_far
    status = "✓ 성공" if last_step_success else "✗ 실패"

    remaining_desc = ""
    if remaining_steps:
        lines = []
        for s in remaining_steps:
            b = f" (최대 {s.budget:,}원)" if s.budget else ""
            h = f" | 힌트: {s.hint}" if s.hint else ""
            lines.append(f"  - {s.name}{b}{h}")
        remaining_desc = "현재 남은 계획:\n" + "\n".join(lines)
    else:
        remaining_desc = "남은 계획: 없음"

    completed_desc = ""
    if completed:
        completed_desc = "완료된 단계:\n" + "\n".join(f"  ✓ {s}" for s in completed)

    prompt = (
        f"태스크: {task[:200]}\n"
        f"총 예산: {budget:,}원 | 현재까지 지출: {spent_so_far:,}원 | 잔여: {remaining_budget:,}원\n\n"
        f"{completed_desc}\n\n"
        f"방금 실행: [{status}] {last_step_name}\n"
        f"결과: {last_step_result[:300]}\n\n"
        f"{remaining_desc}\n\n"
        "위 결과를 반영해 남은 계획을 조정하세요. "
        "변경이 불필요하면 현재 남은 계획을 그대로 반환하세요."
    )

    response = client.chat.completions.create(
        model=model,
        max_tokens=512,
        messages=[
            {"role": "system", "content": _REVIEW_SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    raw = response.choices[0].message.content.strip()

    # reasoning 필드 파싱 후 steps만 추출
    try:
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
        parsed = json.loads(cleaned)
        if "reasoning" in parsed:
            print(f"    [Planner] {parsed['reasoning']}")
        steps_raw = parsed.get("steps", [])
        if steps_raw:
            return [
                PlanStep(
                    name=str(s.get("name", "")).strip(),
                    budget=int(s.get("budget", 0) or 0),
                    hint=str(s.get("hint", "")).strip(),
                )
                for s in steps_raw
                if isinstance(s, dict) and s.get("name")
            ]
    except Exception:
        pass

    # 파싱 실패 시 기존 remaining_steps 그대로 반환
    return remaining_steps
