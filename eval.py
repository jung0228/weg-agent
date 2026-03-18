"""
eval.py — LLM-as-Judge 평가 모듈
에이전트 결과물을 Claude가 루브릭 기반으로 채점한다.
"""
import os
import json

import openai
from tasks import Task
from agent import AgentResult, LETSUR_BASE_URL


MODEL = "gemini-3-flash-preview"

JUDGE_SYSTEM = """당신은 웹 에이전트의 결과물을 평가하는 심사위원입니다.
에이전트가 수행한 PC 견적 태스크의 결과를 아래 루브릭에 따라 평가하세요.

## 평가 루브릭 (각 항목 0~10점)

1. **예산 준수** (budget_compliance): 총 견적 가격이 예산 범위 내인가?
   - 10점: 예산 이하이며 90% 이상 활용
   - 7점: 예산 이하이지만 70% 미만 활용 (너무 저렴하게 구성)
   - 3점: 예산 초과 5% 이내
   - 0점: 예산 크게 초과 또는 가격 정보 없음

2. **부품 완성도** (parts_completeness): 필수 부품이 모두 포함되었는가?
   - 10점: CPU·메인보드·RAM·SSD 모두 포함 (게이밍이면 GPU 포함)
   - 6점: 핵심 부품 3개 포함
   - 3점: 2개 이하
   - 0점: 부품 목록 없음

3. **구체성** (specificity): 모델명과 가격이 구체적으로 제시되었는가?
   - 10점: 각 부품 모델명 + 다나와 실제 가격 명시
   - 6점: 모델명은 있으나 가격 일부 누락
   - 3점: 모델명 없이 카테고리만 언급
   - 0점: 추상적 설명만

4. **목적 적합성** (purpose_fit): 사용 목적(사무/게이밍/최저가)에 맞는 구성인가?
   - 10점: 목적에 최적화된 부품 선택
   - 6점: 대체로 적합하나 일부 아쉬운 선택
   - 3점: 목적과 맞지 않는 부품 선택
   - 0점: 목적 고려 없음

5. **태스크 완료** (task_completion): 에이전트가 DONE으로 명확히 완료했는가?
   - 10점: DONE과 함께 명확한 최종 답변
   - 5점: 완료는 했으나 답변 불명확
   - 0점: DONE 없이 중단

## 출력 형식 (반드시 JSON)
{
  "scores": {
    "budget_compliance": <0-10>,
    "parts_completeness": <0-10>,
    "specificity": <0-10>,
    "purpose_fit": <0-10>,
    "task_completion": <0-10>
  },
  "total": <0-50>,
  "grade": "<S|A|B|C|F>",
  "comment": "<총평 2-3문장>"
}
"""


def _grade(total: int) -> str:
    if total >= 45: return "S"
    if total >= 38: return "A"
    if total >= 28: return "B"
    if total >= 18: return "C"
    return "F"


def evaluate(task: Task, result: AgentResult, api_key: str | None = None) -> dict:
    """에이전트 결과를 LLM-as-Judge로 평가하고 점수 dict 반환"""

    client = openai.OpenAI(
        base_url=LETSUR_BASE_URL,
        api_key=api_key or os.environ["LETSUR_API_KEY"],
    )

    # 에이전트 스텝 요약 (스크린샷 제외)
    steps_summary = "\n".join(
        f"Step {s.step}: [{s.action_raw}] → {s.observation}"
        for s in result.steps
    )

    user_prompt = f"""## 태스크
{task.description}

## 예산
{task.budget:,}원

## 사용 목적
{task.purpose}

## 에이전트 실행 과정
{steps_summary}

## 에이전트 최종 답변
{result.final_answer}

위 결과를 루브릭에 따라 평가해주세요. 반드시 JSON 형식으로만 출력하세요."""

    response = client.chat.completions.create(
        model=MODEL,
        max_completion_tokens=1024,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
    )

    raw = response.choices[0].message.content.strip()

    # JSON 파싱
    try:
        # ```json ... ``` 블록 처리
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        eval_result = json.loads(raw)
    except Exception:
        eval_result = {
            "scores": {},
            "total": 0,
            "grade": "F",
            "comment": f"파싱 실패: {raw[:200]}",
        }

    # grade 재계산 (LLM이 잘못 줄 경우 대비)
    if "total" in eval_result:
        eval_result["grade"] = _grade(eval_result["total"])

    return eval_result


def print_eval(task: Task, eval_result: dict):
    print(f"\n{'='*60}")
    print(f"[평가 결과] {task.id} — {task.purpose} {task.budget:,}원")
    print(f"{'='*60}")
    scores = eval_result.get("scores", {})
    for k, v in scores.items():
        bar = "█" * v + "░" * (10 - v)
        print(f"  {k:<22} {bar} {v}/10")
    print(f"\n  총점: {eval_result.get('total', '?')}/50  등급: {eval_result.get('grade', '?')}")
    print(f"\n  총평: {eval_result.get('comment', '')}")
    print(f"{'='*60}")
