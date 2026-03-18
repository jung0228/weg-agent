"""
actions.py — 좌표 기반 브라우저 액션
LLM이 스크린샷에서 직접 픽셀 좌표를 추론해서 액션을 출력한다.
"""
import re
from dataclasses import dataclass
from typing import Literal

from playwright.async_api import Page


ActionType = Literal[
    "click", "type", "type_enter", "scroll",
    "goto", "back", "wait", "done", "tool"
]


@dataclass
class Action:
    type: ActionType
    x: float | None = None        # 클릭/입력 좌표 x
    y: float | None = None        # 클릭/입력 좌표 y
    value: str | None = None      # type 텍스트, goto URL, done 메시지, tool 이름
    direction: str | None = None  # scroll: up | down
    tool_args: str | None = None  # TOOL 명령 인자


def parse_action(raw: str) -> Action:
    """
    LLM 출력에서 좌표 기반 액션을 파싱한다.

    포맷:
      CLICK (423, 187)
      TYPE (423, 187) "검색어"
      TYPE_ENTER (423, 187) "검색어"   ← 입력 후 Enter
      SCROLL DOWN  /  SCROLL UP
      GOTO https://...
      BACK
      WAIT
      DONE "요약"
      DONE "요약 | 부품:카테고리 | 이름:제품명 | 가격:숫자"
    """
    raw = raw.strip()

    # CLICK (x, y)
    if m := re.search(r"CLICK\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)", raw, re.I):
        return Action(type="click", x=float(m.group(1)), y=float(m.group(2)))

    # TYPE_ENTER (x, y) "text"  — TYPE 보다 먼저 매칭
    if m := re.search(r'TYPE_ENTER\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)\s*"([^"]*)"', raw, re.I):
        return Action(type="type_enter", x=float(m.group(1)), y=float(m.group(2)), value=m.group(3))

    # TYPE (x, y) "text"
    if m := re.search(r'TYPE\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)\s*"([^"]*)"', raw, re.I):
        return Action(type="type", x=float(m.group(1)), y=float(m.group(2)), value=m.group(3))

    # SCROLL DOWN / UP
    if m := re.search(r"SCROLL\s+(DOWN|UP)", raw, re.I):
        return Action(type="scroll", direction=m.group(1).lower())

    # GOTO url
    if m := re.search(r"GOTO\s+(https?://\S+)", raw, re.I):
        return Action(type="goto", value=m.group(1))

    # TOOL name [args]  — 좌표 없는 DOM 기반 고수준 액션
    if m := re.search(r"TOOL\s+(\w+)(?:\s+(.+))?", raw, re.I):
        return Action(type="tool", value=m.group(1), tool_args=(m.group(2) or "").strip())

    if re.search(r"\bBACK\b", raw, re.I):
        return Action(type="back")

    if re.search(r"\bWAIT\b", raw, re.I):
        return Action(type="wait")

    if m := re.search(r'DONE\s+"([^"]*)"', raw, re.I):
        return Action(type="done", value=m.group(1))

    if re.search(r"\bDONE\b", raw, re.I):
        return Action(type="done", value=raw)

    raise ValueError(f"액션 파싱 실패: {raw!r}")


async def execute(action: Action, page: Page) -> str:
    """액션을 실행하고 결과 문자열을 반환한다."""

    if action.type == "click":
        await page.mouse.click(action.x, action.y)
        await page.wait_for_load_state("domcontentloaded", timeout=8000)
        return f"Clicked ({action.x}, {action.y})"

    elif action.type == "type":
        await page.mouse.click(action.x, action.y)
        await page.wait_for_timeout(300)
        await page.keyboard.type(action.value or "")
        return f"Typed '{action.value}' at ({action.x}, {action.y})"

    elif action.type == "type_enter":
        await page.mouse.click(action.x, action.y)
        await page.wait_for_timeout(300)
        await page.keyboard.type(action.value or "")
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("domcontentloaded", timeout=8000)
        return f"Typed '{action.value}' + Enter at ({action.x}, {action.y})"

    elif action.type == "scroll":
        delta = -600 if action.direction == "up" else 600
        await page.mouse.wheel(0, delta)
        await page.wait_for_timeout(400)
        return f"Scrolled {action.direction}"

    elif action.type == "goto":
        await page.goto(action.value, wait_until="domcontentloaded", timeout=15000)
        return f"Navigated to {action.value}"

    elif action.type == "back":
        await page.go_back(wait_until="domcontentloaded", timeout=8000)
        return "Went back"

    elif action.type == "wait":
        await page.wait_for_timeout(2000)
        return "Waited 2s"

    elif action.type == "tool":
        # tools.py의 execute_tool로 위임 (executor에서 직접 호출)
        raise NotImplementedError("TOOL 액션은 executor에서 직접 처리합니다")

    elif action.type == "done":
        return f"DONE: {action.value}"

    return "Unknown action"
