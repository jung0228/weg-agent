"""
planner.py — 고수준 계획 수립 (1회 LLM 호출)
태스크를 독립 실행 가능한 서브태스크 목록으로 분해한다.
"""
import json
import re

import openai


PLAN_SYSTEM = """당신은 웹 에이전트의 계획 수립자입니다.
주어진 태스크를 순서대로 실행 가능한 구체적인 단계로 분해하세요.

## 규칙
- 각 단계는 한 번의 집중된 액션 흐름으로 완료 가능해야 함
- 너무 잘게 쪼개지 말 것 (적정 수준: 4~7단계)
- 다나와 PC 견적 태스크 특성상, 부품 카테고리별로 단계를 나누는 것이 좋음
- 마지막 단계는 반드시 "최종 견적 확인 및 결과 정리"

## 출력 형식
반드시 아래 JSON 형식만 출력하세요. 다른 텍스트, 설명, 마크다운 없이 JSON만:
{"steps": ["단계1", "단계2", "단계3"]}
"""


def _extract_steps(raw: str) -> list[str]:
    """
    LLM 응답에서 steps 리스트를 추출한다.
    Gemini 등이 JSON 앞뒤에 preamble을 붙이는 경우도 처리.
    """
    # 1. 코드 블록 제거
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    # 2. 응답 전체가 JSON이면 바로 파싱
    try:
        data = json.loads(cleaned)
        steps = data.get("steps", [])
        if steps:
            return [str(s).strip() for s in steps if str(s).strip()]
    except Exception:
        pass

    # 3. 응답 내에서 {"steps": [...]} 패턴 찾기 (preamble 있어도 처리)
    m = re.search(r'\{[^{}]*"steps"\s*:\s*(\[[^\[\]]*\])[^{}]*\}', cleaned, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            steps = data.get("steps", [])
            if steps:
                return [str(s).strip() for s in steps if str(s).strip()]
        except Exception:
            pass

    # 4. 마지막 fallback: 번호 붙은 줄 파싱 (1. ... / 2. ...)
    steps = []
    for line in cleaned.splitlines():
        line = re.sub(r'^\s*[\d]+[.)]\s*', "", line).strip()
        # JSON 문법 문자 제거
        line = line.strip('",[]{} ')
        if len(line) > 5:  # 너무 짧은 건 JSON 잔재
            steps.append(line)
    return steps or ["태스크 전체를 한 번에 처리"]


def create_plan(task: str, client: openai.OpenAI, model: str) -> list[str]:
    """태스크를 서브태스크 목록으로 분해한다."""
    response = client.chat.completions.create(
        model=model,
        max_tokens=512,
        messages=[
            {"role": "system", "content": PLAN_SYSTEM},
            {"role": "user", "content": f"태스크:\n{task}"},
        ],
    )
    raw = response.choices[0].message.content.strip()
    return _extract_steps(raw)


def replan(
    task: str,
    completed: list[str],
    failed_step: str,
    memory_context: str,
    client: openai.OpenAI,
    model: str,
) -> list[str]:
    """실패한 단계 이후 남은 계획을 재수립한다."""
    prompt = (
        f"원래 태스크:\n{task}\n\n"
        f"완료된 단계:\n" + "\n".join(f"  ✓ {s}" for s in completed) + "\n\n"
        f"실패한 단계: {failed_step}\n\n"
        f"{memory_context}\n\n"
        "위 상태에서 남은 태스크를 완료하기 위한 새 계획을 수립하세요."
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
