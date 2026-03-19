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


MAX_EXEC_STEPS = 15


_EXEC_SYSTEM_TMPL = """\
당신은 웹 브라우저를 시각적으로 제어하는 에이전트입니다.
스크린샷을 관찰하고, 필요한 곳을 클릭/입력해서 목표를 달성합니다.

{memory_context}

## 현재 목표
{goal}

## 액션 형식

CLICK (x, y)              ← 픽셀 좌표 클릭
CLICK [N]                 ← 스크린샷 번호 배지([N]) 클릭 — 번호가 보일 때 권장
TYPE_ENTER (x, y) "텍스트" ← 클릭 후 입력 + Enter
TYPE_ENTER [N] "텍스트"    ← 번호 배지 입력창 선택 후 텍스트 입력 + Enter
SCROLL DOWN / SCROLL UP
GOTO https://...
SEARCH "쿼리"             ← 네이버 검색 (현재 페이지에서 막혔을 때)
BACK
WAIT

DONE "요약"
DONE "요약 | 부품:카테고리 | 이름:제품명 | 가격:숫자"

## 출력 형식 (반드시 이 순서)
Eval: <이전 액션 결과 — Success / Failed / N/A>
Memory: <기억할 정보 (제품명, 가격 등). 없으면 ->
Predict: <이 액션 실행 시 예상 결과>
Goal: <다음 액션 의도>
Action: <위 액션 중 하나>

## 핵심 규칙
- **스크린샷을 꼼꼼히 보고** 어떤 UI 요소가 있는지 파악한 후 액션 결정
- **번호 배지([N])가 스크린샷에 있으면** CLICK [N] 사용 — 좌표보다 정확함
- **목표에 예산이 명시된 경우** 해당 금액 이하 제품만 선택
- **같은 액션을 반복하지 말 것** — 실패 시 다른 방법 시도
- **막혔을 때**: SCROLL DOWN으로 더 보거나, BACK으로 이전 페이지, SEARCH로 우회
- 뷰포트: {width}×{height}px
- 한 번에 액션 하나만
- DONE은 목표 완전 달성 시만
- WAIT은 페이지 로딩 중일 때만
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
                        "아직 미완료라면 다음 CLICK 또는 SCROLL 액션을 출력하세요."
                    )
            else:
                try:
                    # SOM 번호 [N] → 픽셀 좌표 변환 (SOM_MODE=1일 때만 실질 동작)
                    resolved_raw = _resolve_som_refs(action_raw, state.elements_by_id)
                    if resolved_raw != action_raw:
                        print(f"      SOM: {action_raw!r} → {resolved_raw!r}")
                    action = parse_action(resolved_raw)
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

        # 실패 요약 — 마지막 시도한 액션들 포함 (review_plan이 다른 전략 선택에 활용)
        last_actions = [s.action_raw for s in exec_steps[-4:] if s.action_raw]
        tried = " → ".join(a[:30] for a in last_actions) if last_actions else "없음"
        return StepResult(
            success=False,
            summary=f"최대 {max_steps}스텝 초과 — 미완료. 마지막 시도: {tried}",
            steps=exec_steps,
        )


# ── 헬퍼 ──────────────────────────────────────────────────────────

def _resolve_som_refs(action_raw: str, elements_by_id: dict) -> str:
    """
    SOM 번호 참조를 픽셀 좌표로 변환한다.

    예:
      "CLICK [5]"              → "CLICK (640, 320)"
      "TYPE_ENTER [3] \"텍스트\"" → "TYPE_ENTER (200, 150) \"텍스트\""

    elements_by_id가 비어있거나 해당 번호가 없으면 원본 반환.
    """
    if not elements_by_id:
        return action_raw

    # CLICK [N]
    import re as _re
    def _replace_click(m):
        n = int(m.group(1))
        el = elements_by_id.get(n)
        if el:
            return f"CLICK ({el['x']}, {el['y']})"
        return m.group(0)  # 번호 없으면 원본 유지

    action_raw = _re.sub(r"CLICK\s*\[(\d+)\]", _replace_click, action_raw, flags=_re.I)

    # TYPE_ENTER [N] "text"
    def _replace_type_enter(m):
        n = int(m.group(1))
        text = m.group(2)
        el = elements_by_id.get(n)
        if el:
            return f'TYPE_ENTER ({el["x"]}, {el["y"]}) "{text}"'
        return m.group(0)

    action_raw = _re.sub(
        r'TYPE_ENTER\s*\[(\d+)\]\s*"([^"]*)"',
        _replace_type_enter, action_raw, flags=_re.I
    )

    # TYPE [N] "text"
    def _replace_type(m):
        n = int(m.group(1))
        text = m.group(2)
        el = elements_by_id.get(n)
        if el:
            return f'TYPE ({el["x"]}, {el["y"]}) "{text}"'
        return m.group(0)

    action_raw = _re.sub(
        r'TYPE\s*\[(\d+)\]\s*"([^"]*)"',
        _replace_type, action_raw, flags=_re.I
    )

    return action_raw


def _build_message(state: ScreenState, step: int) -> list[dict]:
    """스크린샷 + 페이지 정보를 LLM 메시지로 조립한다."""
    text_block = (
        f"## Step {step}\n"
        f"URL: {state.page_url}\n"
        f"Title: {state.page_title}\n\n"
        f"스크린샷을 보고 좌표를 직접 추론해서 액션을 결정하세요."
    )
    # SOM 모드: 요소 목록 첨부 (SOM_MODE=1일 때만 element_map이 채워짐)
    if state.element_map:
        text_block += f"\n\n{state.element_map}"
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
