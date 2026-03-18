"""
executor.py — 순수 비전 기반 미니 ReAct 루프
스크린샷만 보고 픽셀 좌표로 액션을 실행한다. DOM 수집 없음.
AgentBrain 패턴: Eval / Memory / Predict / Goal / Action
"""
from dataclasses import dataclass, field

import openai
from playwright.async_api import Page

from som import perceive, ScreenState
from actions import parse_action, execute, Action
from memory import WorkingMemory, try_parse_part
from tools import execute_tool


MAX_EXEC_STEPS = 12


_EXEC_SYSTEM_TMPL = """\
당신은 웹 브라우저를 픽셀 좌표로 제어하는 에이전트입니다.
스크린샷을 보고 클릭/입력할 위치의 좌표를 직접 출력합니다.

{memory_context}

## 현재 목표
{goal}

## 다나와 PC 견적 툴 UI 패턴
1. 오른쪽 "PC 주요구성" 패널에 CPU·메인보드·메모리·SSD·케이스·파워 카테고리 있음
2. 카테고리 클릭 → 가운데 영역에 제품 검색/목록 표시
3. 검색어는 브랜드/모델명 (예: "i3-12100", "H610", "DDR4 8GB") — 용도어("사무용") X

## 액션 형식 — 두 가지 방식

### 1. TOOL (권장 — DOM 기반, 신뢰성 높음)
TOOL select_category "CPU"     ← 카테고리 선택 (CPU/메인보드/메모리/SSD/케이스/파워)
TOOL search "i3-12100"         ← 검색창에 쿼리 입력 + 엔터
TOOL sort_cheapest             ← 낮은 가격순 정렬
TOOL get_products              ← 현재 제품 목록 확인 (광고 자동 제외)
TOOL add_product 1             ← n번째 제품 담기 (광고 자동 스킵, 1-indexed)
TOOL remove_part "메인보드"    ← 오른쪽 패널에서 해당 카테고리 부품 삭제
TOOL get_cart                  ← 현재 오른쪽 패널 견적 현황 확인

### 2. 좌표 기반 (TOOL로 처리 안 되는 경우)
CLICK (x, y)
TYPE_ENTER (x, y) "텍스트"
SCROLL DOWN  /  SCROLL UP
GOTO https://...
BACK
WAIT

DONE "요약"
DONE "요약 | 부품:카테고리 | 이름:제품명 | 가격:숫자"

## 권장 워크플로우 (부품 하나 추가)
1. TOOL select_category "CPU"
2. TOOL search "i3-12100"
3. TOOL sort_cheapest
4. TOOL get_products          ← 목록 보고 n 결정 (광고 이미 제외됨)
5. TOOL add_product 1         ← 반드시 TOOL로. 좌표 클릭 금지
6. DONE "... | 부품:CPU | 이름:... | 가격:..."

## 핵심 규칙
- **목표에 "최대 X원 이내" 가 명시된 경우, 반드시 그 금액 이하 제품만 선택**
  - get_products 결과에서 예산 초과 제품은 건너뛰고 예산 범위 내 제품 선택
  - 예산 내 제품이 없으면 DONE 없이 다른 검색어로 재검색
- **TOOL get_products 이후에는 반드시 TOOL add_product N** 으로 담기
  - 추가 필터(체크박스, 라디오버튼)를 좌표로 클릭하지 말 것
  - 제품 목록에 원하는 제품이 있으면 바로 add_product 실행
- **부품 삭제 시 반드시 TOOL remove_part "카테고리"** — X 버튼 좌표 클릭 금지
- **견적 현황 확인은 TOOL get_cart** — 스크린샷으로 추론하지 말 것
- 검색어에 용량/규격을 포함시켜 처음부터 좁혀라
  예: "SSD 256GB", "DDR4 8GB", "H610 메인보드"
- 카테고리 선택 후 필터를 따로 클릭할 필요 없음 — 검색으로 해결

## 출력 형식 (반드시 이 순서)
Eval: <이전 액션 결과 — Success / Failed / N/A>
Memory: <기억할 정보 (제품명, 가격 등). 없으면 ->
Predict: <이 액션 실행 시 예상 결과 — 확신 없으면 다른 액션 선택>
Goal: <다음 액션 의도 한 문장>
Action: <위 형식 중 하나>

## 주의사항
- 뷰포트: {width}×{height}px — 이 범위 안의 좌표만 사용
- 한 번에 액션 하나만
- DONE은 목표가 완전히 달성됐을 때만
- WAIT은 로딩 중일 때만
"""


@dataclass
class ExecStep:
    step: int
    eval_prev: str
    memory_note: str
    predict: str
    goal_intent: str
    action_raw: str
    action: Action | None
    observation: str
    screenshot_b64: str


@dataclass
class StepResult:
    success: bool
    summary: str
    steps: list[ExecStep] = field(default_factory=list)


class Executor:
    def __init__(self, client: openai.OpenAI, model: str):
        self.client = client
        self.model = model

    async def run(
        self,
        goal: str,
        page: Page,
        memory: WorkingMemory,
        max_steps: int = MAX_EXEC_STEPS,
    ) -> StepResult:
        """
        단일 목표를 달성할 때까지 미니 ReAct를 반복한다.
        매 스텝마다 스크린샷을 찍어 LLM에게 전달한다.
        """
        history: list[dict] = []
        exec_steps: list[ExecStep] = []

        system_prompt = _EXEC_SYSTEM_TMPL.format(
            memory_context=memory.to_context(),
            goal=goal,
            width=1280,
            height=800,
        )

        prev_action_raw = ""
        same_action_count = 0
        consec_fail_count = 0

        for step_num in range(1, max_steps + 1):
            # OBSERVE
            state: ScreenState = await perceive(page)
            system_prompt_with_vp = _EXEC_SYSTEM_TMPL.format(
                memory_context=memory.to_context(),
                goal=goal,
                width=state.width,
                height=state.height,
            )
            print(f"    [{step_num}] vision | {state.width}×{state.height}", end="")

            # THINK — 스크린샷 + URL/Title만 전달
            user_content = _build_message(state, step_num)
            history.append({"role": "user", "content": user_content})

            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=512,
                messages=[{"role": "system", "content": system_prompt_with_vp}] + history,
            )
            assistant_text = response.choices[0].message.content
            history.append({"role": "assistant", "content": assistant_text})

            eval_prev, memory_note, predict, goal_intent, action_raw = _parse_brain_output(assistant_text)

            # ACT
            action_error = False
            if not action_raw.strip():
                action = None
                action_error = True
                observation = (
                    "Action: 필드가 비어있습니다. "
                    "목표 달성 시 반드시 DONE \"요약 | 부품:카테고리 | 이름:제품명 | 가격:숫자\" 를 출력하세요. "
                    "아직 미완료라면 다음 TOOL 또는 CLICK 액션을 출력하세요."
                )
            else:
                try:
                    action = parse_action(action_raw)
                    if action.type == "tool":
                        # TOOL 명령 → tools.py 디스패처로 위임
                        observation = await execute_tool(action.value or "", action.tool_args or "", page)
                    else:
                        observation = await execute(action, page)
                except Exception as e:
                    action = None
                    action_error = True
                    observation = f"에러: {e}"

            exec_steps.append(ExecStep(
                step=step_num,
                eval_prev=eval_prev,
                memory_note=memory_note,
                predict=predict,
                goal_intent=goal_intent,
                action_raw=action_raw,
                action=action,
                observation=observation,
                screenshot_b64=state.screenshot_b64,
            ))

            mode = "tool" if (action and action.type == "tool") else "vision"
            predict_short = f" → {predict[:35]}" if predict else ""
            print(f" | {mode} | {eval_prev[:12]} | {action_raw[:45]}{predict_short}")

            # 루프/에러 감지 (로깅용)
            if action_raw == prev_action_raw:
                same_action_count += 1
                if same_action_count >= 3:
                    print(f"    ⚠ 동일 액션 {same_action_count}회 반복")
            else:
                same_action_count = 0
            prev_action_raw = action_raw

            if eval_prev.lower().startswith("fail") or action_error:
                consec_fail_count += 1
            else:
                consec_fail_count = 0

            # DONE 체크
            if action and action.type == "done":
                summary = action.value or observation

                part = try_parse_part(summary)
                if part:
                    cat, name, price = part
                    memory.add_part(cat, name, price)
                    print(f"    → 부품 추가: {cat} / {name} / {price:,}원")

                if memory_note and memory_note != "-":
                    memory.scratchpad += f"\n[{goal[:20]}] {memory_note}"

                return StepResult(success=True, summary=summary, steps=exec_steps)

            history.append({
                "role": "user",
                "content": f"Observation: {observation}",
            })

        return StepResult(
            success=False,
            summary=f"최대 {max_steps}스텝 초과 — 미완료",
            steps=exec_steps,
        )


# ── 헬퍼 ──────────────────────────────────────────────────────────

def _build_message(state: ScreenState, step: int) -> list[dict]:
    """스크린샷 + 페이지 정보를 LLM 메시지로 조립한다."""
    text_block = (
        f"## Step {step}\n"
        f"URL: {state.page_url}\n"
        f"Title: {state.page_title}\n\n"
        f"스크린샷을 보고 좌표를 직접 추론해서 액션을 결정하세요."
    )
    return [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{state.screenshot_b64}"},
        },
        {"type": "text", "text": text_block},
    ]


def _parse_brain_output(text: str) -> tuple[str, str, str, str, str]:
    """AgentBrain 5-field 파싱: Eval / Memory / Predict / Goal / Action"""
    eval_prev = memory_note = predict = goal_intent = action_raw = ""
    for line in text.splitlines():
        if line.startswith("Eval:"):
            eval_prev = line[5:].strip()
        elif line.startswith("Memory:"):
            memory_note = line[7:].strip()
        elif line.startswith("Predict:"):
            predict = line[8:].strip()
        elif line.startswith("Goal:"):
            goal_intent = line[5:].strip()
        elif line.startswith("Action:"):
            action_raw = line[7:].strip()
    return eval_prev, memory_note, predict, goal_intent, action_raw
