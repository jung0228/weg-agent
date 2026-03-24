"""
step_logger.py — weg-agent 스텝별 구조화 저장
Personalized-Web-Agent 포맷과 동일한 디렉토리 구조로 저장

저장 구조:
  <task_dir>/
    S1/
      metadata.json      - 스텝 번호, URL, action, eval, memory, goal
      som_image.png      - 스크린샷 (browser-use가 SoM 오버레이 포함)
      user_prompt.txt    - LLM 입력: 태스크 + 인터랙티브 요소 + 히스토리
      system_prompt.txt  - 시스템 프롬프트 (첫 스텝에만)
      acc_tree.txt       - DOM 접근성 트리 (요소 목록)
    S2/
      ...
"""

import base64
import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from browser_use.agent.service import Agent


# 요소 타입 매핑 (태그명 → 대문자 타입)
_TAG_TYPE = {
    "a": "A",
    "button": "BUTTON",
    "input": "INPUT",
    "select": "SELECT",
    "textarea": "TEXTAREA",
    "div": "DIV",
    "span": "SPAN",
    "li": "LI",
    "img": "IMG",
    "form": "FORM",
}


def _get_element_type(node) -> str:
    tag = getattr(node, "tag_name", "") or ""
    return _TAG_TYPE.get(tag.lower(), tag.upper() or "ELEM")


def _get_element_text(node) -> str:
    """요소의 텍스트 또는 값 추출"""
    text = ""
    # input placeholder / value
    attrs = getattr(node, "attributes", {}) or {}
    if attrs.get("placeholder"):
        text = attrs["placeholder"]
    elif attrs.get("value"):
        text = attrs["value"]
    elif attrs.get("aria-label"):
        text = attrs["aria-label"]
    elif attrs.get("title"):
        text = attrs["title"]
    # 텍스트 콘텐츠
    if not text:
        text = (getattr(node, "text", "") or "").strip()
    # 옵션 목록 (SELECT)
    if _get_element_type(node) == "SELECT":
        children = getattr(node, "children", []) or []
        opts = [
            (getattr(c, "text", "") or "").strip()
            for c in children
            if (getattr(c, "text", "") or "").strip()
        ]
        if opts:
            text = "".join(opts[:6])  # 최대 6개
    return text[:80]  # 80자 제한


def _build_acc_tree(dom_state) -> str:
    """
    DOM selector_map → acc_tree.txt 형식
    [index] [TYPE] [text]
    """
    if dom_state is None:
        return "(DOM 없음)\n"

    selector_map = getattr(dom_state, "selector_map", {}) or {}
    lines = []
    for idx in sorted(selector_map.keys(), key=int):
        node = selector_map[idx]
        etype = _get_element_type(node)
        text = _get_element_text(node)
        lines.append(f"[{idx}] [{etype}] [{text}]")
    return "\n".join(lines) if lines else "(인터랙티브 요소 없음)\n"


def _build_user_prompt(task: str, history_actions: list[str], acc_tree: str) -> str:
    """
    Personalized-Web-Agent user_prompt.txt 형식과 동일하게 생성
    """
    hist_str = str(history_actions) if history_actions else "[]"
    return (
        f"Here is the screenshot image: <|image_1|>\n"
        f"The instruction is to {task}\n"
        f"History actions:\n{hist_str}\n"
        f"Here is the screen information:\n"
        f"{acc_tree}\n"
        f"Think about what you need to do with current screen, "
        f"and output the action in the required format in the end."
    )


def _action_to_str(action_list) -> str:
    """AgentOutput.action 리스트 → 사람이 읽기 쉬운 문자열"""
    if not action_list:
        return ""
    parts = []
    for act in action_list:
        if hasattr(act, "model_dump"):
            d = act.model_dump(exclude_none=True)
        elif isinstance(act, dict):
            d = act
        else:
            d = {"action": str(act)}
        parts.append(json.dumps(d, ensure_ascii=False))
    return "\n".join(parts)


def save_run_steps(agent: "Agent", task_dir: Path, task: str) -> None:
    """
    agent.history를 순회해서 스텝별 데이터를 저장.
    eval runner에서 agent.run() 완료 후 호출.
    """
    history = agent.history  # AgentHistoryList
    steps = history.history  # list[AgentHistory]

    history_actions: list[str] = []

    for i, step in enumerate(steps):
        step_dir = task_dir / f"S{i + 1}"
        step_dir.mkdir(parents=True, exist_ok=True)

        # ── 1. som_image.png ────────────────────────────────────────────
        # browser-use는 screenshot_path 또는 base64 screenshot 저장
        screenshot_saved = False

        # state_message에서 screenshot 추출 시도
        state_msg = getattr(step, "state_message", None)
        if state_msg and hasattr(state_msg, "content"):
            for part in (state_msg.content if isinstance(state_msg.content, list) else []):
                if getattr(part, "type", "") == "image_url":
                    url = getattr(part, "image_url", {})
                    data_url = url.get("url", "") if isinstance(url, dict) else getattr(url, "url", "")
                    if data_url.startswith("data:image"):
                        b64data = data_url.split(",", 1)[1]
                        (step_dir / "som_image.png").write_bytes(base64.b64decode(b64data))
                        screenshot_saved = True
                        break

        # BrowserStateHistory.screenshot_path 시도
        if not screenshot_saved:
            state = getattr(step, "state", None)
            sp = getattr(state, "screenshot_path", None) if state else None
            if sp and Path(sp).exists():
                shutil.copy(sp, step_dir / "som_image.png")
                screenshot_saved = True

        # task_dir 내 스크린샷 파일 매핑 시도 (eval runner가 저장한 screenshot{n}.png)
        if not screenshot_saved:
            candidate = task_dir / f"screenshot{i + 1}.png"
            if candidate.exists():
                shutil.copy(candidate, step_dir / "som_image.png")
                screenshot_saved = True

        # ── 2. acc_tree.txt ─────────────────────────────────────────────
        dom_state = None
        state_summary = getattr(step, "state", None)  # BrowserStateHistory
        # BrowserStateHistory에는 dom_state 없음 → state_message에서 추출 시도
        if state_msg and hasattr(state_msg, "content"):
            for part in (state_msg.content if isinstance(state_msg.content, list) else []):
                if getattr(part, "type", "") == "text":
                    raw_text = getattr(part, "text", "")
                    # acc_tree는 user_prompt 안에 있는 요소 목록으로 대체
                    # (DOM state가 없으면 텍스트 파싱)
                    break

        acc_tree = _build_acc_tree(dom_state)

        # state_message 텍스트에서 요소 목록 추출 (fallback)
        if acc_tree.startswith("(DOM") and state_msg:
            import re
            raw = ""
            content = getattr(state_msg, "content", "")
            if isinstance(content, list):
                for part in content:
                    if getattr(part, "type", "") == "text":
                        raw = getattr(part, "text", "")
                        break
            elif isinstance(content, str):
                raw = content
            # 인터랙티브 요소 패턴 추출
            matches = re.findall(r"\[(\d+)\][^\[]+\[([A-Z]+)\][^\[]*\[([^\]]*)\]", raw)
            if matches:
                acc_tree = "\n".join(f"[{idx}] [{etype}] [{text}]" for idx, etype, text in matches)

        (step_dir / "acc_tree.txt").write_text(acc_tree, encoding="utf-8")

        # ── 3. user_prompt.txt ──────────────────────────────────────────
        user_prompt = _build_user_prompt(task, history_actions.copy(), acc_tree)
        (step_dir / "user_prompt.txt").write_text(user_prompt, encoding="utf-8")

        # ── 4. system_prompt.txt (첫 스텝에만) ─────────────────────────
        if i == 0:
            sys_prompt = "weg-agent browser-use based agent\n"
            try:
                msg_mgr = getattr(agent, "_message_manager", None)
                if msg_mgr:
                    history_state = getattr(msg_mgr, "history", None)
                    if history_state and hasattr(history_state, "messages"):
                        for msg in history_state.messages:
                            role = getattr(msg, "role", "") or ""
                            if "system" in str(role).lower():
                                content = getattr(msg, "content", "")
                                if isinstance(content, str):
                                    sys_prompt = content
                                break
            except Exception:
                pass
            (step_dir / "system_prompt.txt").write_text(sys_prompt, encoding="utf-8")

        # ── 5. metadata.json ────────────────────────────────────────────
        model_out = getattr(step, "model_output", None)
        action_str = _action_to_str(getattr(model_out, "action", []) if model_out else [])

        url = ""
        state_h = getattr(step, "state", None)
        if state_h:
            url = getattr(state_h, "url", "") or ""

        metadata = {
            "step": i + 1,
            "total_steps": len(steps),
            "url": url,
            "evaluation_previous_goal": getattr(model_out, "evaluation_previous_goal", "") if model_out else "",
            "memory": getattr(model_out, "memory", "") if model_out else "",
            "next_goal": getattr(model_out, "next_goal", "") if model_out else "",
            "action": action_str,
            "screenshot_saved": screenshot_saved,
        }
        (step_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 히스토리에 이번 액션 추가
        if action_str:
            history_actions.append(action_str)

    print(f"  📁 {len(steps)}개 스텝 저장 → {task_dir}/S1~S{len(steps)}")
