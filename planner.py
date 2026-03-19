"""
planner.py — 고수준 계획 수립 (1회 LLM 호출)
태스크를 독립 실행 가능한 서브태스크 목록으로 분해한다.
각 단계에 부품별 예산 상한 + 필터 힌트(선택)를 배분한다.
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


def replan(
    task: str,
    budget: int,
    completed: list[str],
    failed_step: str,
    memory_context: str,
    client: openai.OpenAI,
    model: str,
) -> list[PlanStep]:
    """실패한 단계 이후 남은 계획을 재수립한다."""
    prompt = (
        f"원래 태스크: {task}\n총 예산: {budget:,}원\n\n"
        f"완료된 단계:\n" + "\n".join(f"  ✓ {s}" for s in completed) + "\n\n"
        f"실패한 단계: {failed_step}\n\n"
        f"{memory_context}\n\n"
        "위 상태에서 남은 태스크를 완료하기 위한 새 계획을 수립하세요. "
        "잔여 예산에 맞게 각 부품 예산을 재배분하세요."
    )
    response = client.chat.completions.create(
        model=model,
        max_tokens=512,
        messages=[
            {"role": "system", "content": PLAN_SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    raw = response.choices[0].message.content.strip()
    return _extract_steps(raw)
