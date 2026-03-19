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

## 모델별 실제 시세 (다나와 기준, 2025년 기준)
힌트는 반드시 아래 시세표를 참고하여 할당 예산 이내 모델을 선택할 것.

| 부품 | 모델 | 시세 | 특징 |
|------|------|------|------|
| CPU | i3-12100F (벌크) | 140,000~150,000원 | LGA1700, 내장그래픽 없음 (GPU 필요) |
| CPU | i3-12100 (벌크) | 220,000~240,000원 | LGA1700, 내장그래픽 있음 |
| CPU | i3-13100F (벌크) | 145,000~155,000원 | LGA1700, 내장그래픽 없음 (GPU 필요) |
| CPU | i3-13100 (벌크) | 200,000~230,000원 | LGA1700, 내장그래픽 있음 |
| CPU | 인텔 프로세서 300 (벌크) | 150,000~165,000원 | LGA1700, 내장그래픽 있음, 저가형 |
| CPU | Ryzen 5 5600G | 110,000~130,000원 | AM4, 내장그래픽 포함, 사무용 권장 |
| CPU | Ryzen 5 4600G | 90,000~110,000원 | AM4, 내장그래픽 포함, 사무용 저가 |
| CPU | i5-12400F | 130,000~150,000원 | LGA1700, 내장그래픽 없음, 게이밍 |
| CPU | i5-13400F | 145,000~170,000원 | LGA1700, 내장그래픽 없음, 게이밍 |
※ G7400/G6900 단종 — 현재 다나와 미판매
| 메인보드 | H610M 최저가 | 60,000~80,000원 | LGA1700, 사무용 |
| 메인보드 | B660M | 90,000~130,000원 | LGA1700, 보급 게이밍 |
| 메모리 | DDR4 8GB | 20,000~30,000원 | 사무용 최소 |
| 메모리 | DDR4 16GB | 35,000~50,000원 | 게이밍 권장 |
| SSD | 256GB NVMe | 25,000~40,000원 | 사무용 최소 (검색어: "256GB") |
| SSD | 500GB NVMe | 40,000~60,000원 | 게이밍 권장 (검색어: "500GB" 또는 "1TB") |
| 케이스 | 미니타워 | 25,000~45,000원 | 사무용 |
| 파워 | 400~500W | 35,000~55,000원 | 사무용 |
| GPU | RTX 4060 | 340,000~380,000원 | 게이밍 |

## 목적별 예산 배분 가이드

### 사무용 (30만~60만원)
힌트 모델은 반드시 할당 예산 이내 시세인 것을 선택할 것.
- CPU (내장그래픽 필수): 예산의 13~18%
  - 50만원 → 사무용 내장그래픽 필수 → **Ryzen 5 5600G** (AM4, ~120,000원) 권장
  - 50만원 인텔 소켓1700 → 내장그래픽 저가 단종 → i3-12100 (벌크) ~225,000원으로 예산 부족
  - 사무용 저예산에서 내장그래픽 필요하면 **AMD Ryzen G 시리즈** 추천
- 메인보드: 예산의 12~16% → H610M LGA1700 (60,000~80,000원)
- 메모리: 예산의 6~8% → DDR4 8GB (20,000~30,000원)
- SSD: 예산의 7~10% → hint는 "256GB NVMe" (카테고리+필터 방식: filter "256GB" + filter "M.2 (NVMe)")
- 케이스: 예산의 6~9% → 미니타워 (25,000~45,000원)
- 파워: 예산의 8~12% → 400W 80Plus (35,000~55,000원)

### 게이밍 (80만~150만원)
- CPU: 예산의 15~20% → i5-13400F (145,000~170,000원), Ryzen 5 7600
- GPU: 예산의 30~38% → RTX 4060, RTX 4060Ti, RX 7600
- 메인보드: 예산의 10~14% → B660M, B760M (LGA1700)
- 메모리: 예산의 5~8% → DDR4 16GB
- SSD: 예산의 6~9% → hint는 "1TB" 또는 "500GB"
- 케이스+파워: 예산의 12~17%

### 저예산 (30만원 미만)
- CPU: 내장그래픽 필수 → Celeron G6900 (60,000~75,000원)
- 메인보드: H610M 최저가 (60,000~75,000원)
- 메모리: DDR4 8GB
- SSD: SSD 128~256GB

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
