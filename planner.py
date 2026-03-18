"""
planner.py — 고수준 계획 수립 (1회 LLM 호출)
태스크를 독립 실행 가능한 서브태스크 목록으로 분해한다.
각 단계에 부품별 예산 상한 + 검색 힌트를 함께 배분한다.
"""
import json
import re
from dataclasses import dataclass

import openai


@dataclass
class PlanStep:
    name: str          # 단계 이름 (예: "CPU 선택")
    budget: int        # 이 부품에 쓸 최대 예산 (원), 0이면 제한 없음
    hint: str          # 추천 검색어/모델 힌트


PLAN_SYSTEM = """\
당신은 PC 견적 웹 에이전트의 계획 수립자입니다.
주어진 예산과 목적에 맞게 각 부품별 예산을 현실적으로 배분하고
가장 적합한 검색 모델 힌트를 제공하세요.

## 예산 배분 원칙
- 모든 부품 예산의 합이 총 예산의 90% 이하가 되도록 (버퍼 확보)
- 단계 수: 4~7개 (마지막은 반드시 "최종 견적 확인 및 결과 정리")
- 힌트는 다나와 검색창에 바로 입력할 구체적인 모델명/규격

## 목적별 예산 배분 가이드

### 사무용 (30만~60만원)
- CPU: 예산의 15~20% → 저전력 사무용 (Celeron G6900, Pentium Gold G7400, i3-12100F)
- 메인보드: 예산의 13~18% → H610 또는 B660 (LGA1700)
- 메모리: 예산의 7~10% → DDR4 8GB
- SSD: 예산의 9~12% → SSD 256GB 또는 SSD 512GB
- 케이스: 예산의 7~9% → 미들타워 케이스
- 파워: 예산의 10~14% → 400W~500W 80Plus

### 게이밍 (80만~150만원)
- CPU: 예산의 18~22% → i5-13400F, i5-12400F, Ryzen 5 7600
- GPU: 예산의 30~38% → RTX 4060, RTX 4060Ti, RX 7600
- 메인보드: 예산의 10~14% → B660, B760 (LGA1700)
- 메모리: 예산의 6~9% → DDR4 16GB
- SSD: 예산의 7~10% → SSD 500GB 또는 SSD 1TB
- 케이스+파워: 예산의 13~18%

### 저예산 (30만원 미만)
- CPU: 내장그래픽 필수 (Celeron G6900, Pentium Gold G7400)
- 메인보드: H610 최저가
- 메모리: DDR4 8GB
- SSD: SSD 128GB

## 출력 형식
반드시 아래 JSON 형식만 출력하세요. 다른 텍스트, 설명, 마크다운 없이 JSON만:
{
  "steps": [
    {"name": "CPU 선택", "budget": 90000, "hint": "Celeron G6900"},
    {"name": "메인보드 선택", "budget": 75000, "hint": "H610 메인보드 LGA1700"},
    {"name": "최종 견적 확인 및 결과 정리", "budget": 0, "hint": ""}
  ]
}
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
