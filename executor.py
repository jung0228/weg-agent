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
from knowledge import DanawaKnowledge, BASE_KNOWLEDGE, load_knowledge


MAX_EXEC_STEPS = 12


_EXEC_SYSTEM_TMPL = """\
당신은 웹 브라우저를 픽셀 좌표로 제어하는 에이전트입니다.
스크린샷을 보고 클릭/입력할 위치의 좌표를 직접 출력합니다.

{memory_context}

{knowledge_context}

## 현재 목표
{goal}

## 액션 형식 — 두 가지 방식

### 1. TOOL (권장 — DOM 기반, 신뢰성 높음)
TOOL select_category "CPU"          ← 카테고리 선택 (CPU/메인보드/메모리/SSD/케이스/파워)
TOOL filter "인텔(소켓1700)"         ← 필터 체크박스 클릭 (레이블 텍스트 그대로)
TOOL filter "DDR4"                  ← 메모리 규격 필터
TOOL filter "인텔"                  ← 제조사 필터
TOOL clear_filters                  ← 현재 카테고리 필터 전체 해제
TOOL search "H610M"                 ← 검색창 입력 (카테고리 내 검색)
TOOL sort_cheapest                  ← 낮은 가격순 정렬
TOOL get_products                   ← 현재 제품 목록 확인 (광고 자동 제외)
TOOL add_product 1                  ← n번째 제품 담기 (광고 자동 스킵, 1-indexed)
TOOL remove_part "메인보드"         ← 오른쪽 패널에서 해당 카테고리 부품 삭제
TOOL get_cart                       ← 현재 오른쪽 패널 견적 현황 확인

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

### ⚠️ 핵심: sort_cheapest는 검색(search) 결과 뷰에서 작동하지 않음
- `TOOL search` 이후에는 **절대 sort_cheapest 사용 금지** → 검색 필터가 리셋됨
- sort_cheapest는 반드시 **`TOOL select_category` 이후 카테고리 뷰**에서만 사용

### 방법 A: 카테고리 + 필터 방식 (sort 사용 가능 — 모든 부품 권장)
CPU 예시:
1. TOOL select_category "CPU"
2. TOOL filter "인텔(소켓1700)"       ← 소켓/규격 필터
3. TOOL sort_cheapest                ← 카테고리 뷰에서만 동작
4. TOOL get_products
5. TOOL add_product 1
6. DONE "... | 부품:CPU | 이름:... | 가격:..."

메모리 예시 (반드시 방법 A 사용 — 검색 절대 금지):
1. TOOL select_category "메모리"
2. TOOL filter "DDR4"                ← 메모리 규격 필터
3. TOOL sort_cheapest
4. TOOL get_products
5. TOOL add_product 1

### 방법 B: 검색 방식 (특정 모델명 알 때 — sort 사용 금지)
1. TOOL select_category "메인보드"
2. TOOL search "H610M"               ← 카테고리 내 검색
3. (**sort_cheapest 사용 금지** — 검색 결과 초기화됨)
4. TOOL get_products                 ← 검색 결과 목록 (이미 관련 제품만 표시됨)
5. TOOL add_product 1                ← 첫 번째 제품이 보통 가성비 제품

### 방법 C: SSD 전용 (카테고리 + 필터 방식 — 검색 절대 금지)
- SSD는 검색 방식이 불안정함 → 반드시 아래 순서 사용
1. TOOL select_category "SSD"
2. TOOL filter "256GB"            ← 용량 필터 (없으면 생략)
3. TOOL filter "M.2 (NVMe)"       ← 인터페이스 필터 (있는 경우에만)
4. TOOL sort_cheapest             ← 카테고리 뷰이므로 sort 가능
5. TOOL get_products
6. TOOL add_product 1

## 핵심 규칙
- **목표에 "최대 X원 이내" 가 명시된 경우, 반드시 그 금액 이하 제품만 선택**
  - get_products 결과에서 예산 초과 제품은 건너뛰고 예산 범위 내 제품 선택
  - 예산 내 제품이 없으면 DONE 없이 필터/검색어 변경 후 재시도
- **목표에 "필수 검색어: X" 가 있으면 반드시 그 검색어만 사용** — 다른 모델로 임의 변경 절대 금지
- **목표에 "참고 모델/규격: X" 가 있으면 방법 A(카테고리+필터)를 우선 사용**, 검색은 차선책
- **TOOL search 이후 TOOL sort_cheapest 절대 금지** — 검색 필터가 리셋됨
  - 검색 후에는 바로 TOOL get_products → TOOL add_product
  - sort_cheapest는 TOOL select_category 이후 카테고리 뷰에서만 사용
  - TOOL search 후 카테고리 탭은 자동 선택됨 — 추가 CLICK으로 탭 클릭 불필요
  - SSD 검색 시: "256GB NVMe SSD" 아닌 "256GB" 처럼 용량만 검색
- **필터 레이블은 화면에 보이는 텍스트 그대로** — 예: "인텔(소켓1700)", "코어i3-12세대", "DDR4"
- **TOOL get_products 이후에는 반드시 TOOL add_product N** 으로 담기
- **부품 삭제 시 반드시 TOOL remove_part "카테고리"** — X 버튼 좌표 클릭 금지
- **견적 현황 확인은 TOOL get_cart** — 스크린샷으로 추론하지 말 것

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
    def __init__(self, client: openai.OpenAI, model: str, knowledge: DanawaKnowledge | None = None):
        self.client = client
        self.model = model
        # 지식이 주입되지 않으면 캐시 또는 BASE_KNOWLEDGE 사용
        self.knowledge = knowledge or load_knowledge()

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
        knowledge_ctx = self.knowledge.to_context()

        prev_action_raw = ""
        same_action_count = 0
        consec_fail_count = 0
        last_add_product_obs = ""  # 마지막 add_product 성공 관측값 (DONE 루프 탈출용)

        for step_num in range(1, max_steps + 1):
            # OBSERVE — page crash 방어 (sort_cheapest 후 페이지 재로드 시 TargetClosedError)
            try:
                state: ScreenState = await perceive(page)
            except Exception as _e:
                if "closed" in str(_e).lower() or "TargetClosed" in type(_e).__name__:
                    # 페이지 재탐색 후 재시도
                    try:
                        await page.goto(
                            "https://shop.danawa.com/virtualestimate/",
                            wait_until="domcontentloaded",
                            timeout=30000,
                        )
                        await page.wait_for_timeout(3000)
                        state: ScreenState = await perceive(page)
                    except Exception:
                        break  # 복구 실패 시 이 executor run 종료
                else:
                    raise
            system_prompt_with_vp = _EXEC_SYSTEM_TMPL.format(
                memory_context=memory.to_context(),
                knowledge_context=knowledge_ctx,
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
                # add_product 성공 후 빈 액션 반복 → DONE 힌트에 제품 정보 포함
                if last_add_product_obs:
                    observation = (
                        f"Action: 필드가 비어있습니다. 제품을 이미 담았습니다: {last_add_product_obs}. "
                        f"반드시 DONE \"목표완료 | 부품:카테고리명 | 이름:제품명 | 가격:숫자\" 형식으로 출력하세요."
                    )
                else:
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
                        # add_product 성공 시 관측값 기록 (DONE 루프 탈출용)
                        if (action.value or "").lower() == "add_product" and "담기 완료" in observation:
                            last_add_product_obs = observation
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
                # add_product 성공 후 빈 Action 2회 이상 반복 → 강제 자동 완료
                if not action_raw.strip() and last_add_product_obs and same_action_count >= 2:
                    auto_summary = f"자동완료(DONE루프탈출) | {last_add_product_obs}"
                    part = try_parse_part(auto_summary)
                    if part:
                        cat, name, price = part
                        memory.add_part(cat, name, price)
                        print(f"    → [자동완료] 부품 추가: {cat} / {name} / {price:,}원")
                    return StepResult(success=True, summary=auto_summary, steps=exec_steps)
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
