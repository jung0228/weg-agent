"""
llm_logger.py — browser-use LLM 실제 입출력 캡처

browser-use의 ChatOpenAI.ainvoke()를 래핑해서
LLM에 보내는 실제 메시지와 응답을 S1/, S2/, ... 폴더에 저장한다.

저장 파일:
  S{n}/
    system_prompt.txt  — 시스템 메시지 원문
    user_prompt.txt    — 유저 메시지 (DOM 요소 + 히스토리 포함)
    som_image.png      — 해당 스텝 스크린샷
    llm_output.json    — LLM 응답 raw
    metadata.json      — 스텝 번호, 소요시간
"""

import base64
import json
import time
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LoggingLLM:
    """
    browser-use ChatOpenAI를 래핑해서 ainvoke 호출마다 입출력 저장.
    ChatOpenAI의 모든 속성/메서드를 투명하게 위임.
    """

    def __init__(self, llm, task_dir: Path, browser_session=None):
        self._llm = llm
        self._task_dir = Path(task_dir)
        self._step = 0
        self._browser_session = browser_session  # optional: SoM debug screenshot

    # ── 투명 위임 ──────────────────────────────────────────────────────
    def __getattr__(self, name: str):
        return getattr(self._llm, name)

    # ── 핵심: ainvoke 가로채기 ─────────────────────────────────────────
    async def ainvoke(self, messages, output_format=None, **kwargs):
        self._step += 1
        sd = self._task_dir / f"S{self._step}"
        sd.mkdir(parents=True, exist_ok=True)
        t0 = time.time()

        # ── 입력 저장 ──────────────────────────────────────────────────
        self._save_input(sd, messages)

        # ── SoM 디버그 스크린샷 (add_highlights 완료 후 시점) ──────────
        await self._save_som_debug(sd)

        # ── 실제 LLM 호출 ──────────────────────────────────────────────
        result = await self._llm.ainvoke(messages, output_format, **kwargs)

        # ── 출력 저장 ──────────────────────────────────────────────────
        elapsed = round(time.time() - t0, 2)
        self._save_output(sd, result, elapsed)

        return result

    # ── SoM 디버그 스크린샷 ────────────────────────────────────────────
    async def _save_som_debug(self, sd: Path) -> None:
        """add_highlights 완료 후 시점에 스크린샷 찍어 som_debug.png 저장."""
        if self._browser_session is None:
            return
        try:
            raw = await self._browser_session.take_screenshot(full_page=False)
            if raw:
                (sd / "som_debug.png").write_bytes(raw)
        except Exception:
            pass

    # ── 저장 헬퍼 ─────────────────────────────────────────────────────

    def _save_input(self, sd: Path, messages) -> None:
        system_parts = []
        user_parts = []
        image_b64 = None

        for msg in messages:
            role = getattr(msg, "role", "") or ""
            content = getattr(msg, "content", "") or ""

            # content가 리스트 (browser-use ContentPartTextParam / ContentPartImageParam)
            if isinstance(content, list):
                for block in content:
                    btype = getattr(block, "type", None) or (block.get("type", "") if isinstance(block, dict) else "")

                    if btype == "text":
                        text = getattr(block, "text", None) or (block.get("text", "") if isinstance(block, dict) else "")
                        (system_parts if role == "system" else user_parts).append(text)

                    elif btype == "image_url":
                        # browser-use: ContentPartImageParam.image_url = ImageURL(url=...)
                        url_obj = getattr(block, "image_url", None) or (block.get("image_url", {}) if isinstance(block, dict) else {})
                        data_url = getattr(url_obj, "url", None) or (url_obj.get("url", "") if isinstance(url_obj, dict) else "")
                        if data_url.startswith("data:image") and image_b64 is None:
                            image_b64 = data_url.split(",", 1)[1]

            # content가 문자열
            elif isinstance(content, str):
                (system_parts if role == "system" else user_parts).append(content)

        (sd / "system_prompt.txt").write_text(
            "\n\n---\n\n".join(system_parts) or "(없음)", encoding="utf-8"
        )

        user_text = "\n\n---\n\n".join(user_parts) or "(없음)"
        (sd / "user_prompt.txt").write_text(user_text, encoding="utf-8")

        # acc_tree.txt — user 메시지 안의 browser_state 블록에서 추출
        acc_tree = self._extract_acc_tree(user_text)
        (sd / "acc_tree.txt").write_text(acc_tree, encoding="utf-8")

        if image_b64:
            (sd / "som_image.png").write_bytes(base64.b64decode(image_b64))

        (sd / "metadata.json").write_text(
            json.dumps({"step": self._step, "status": "running"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _extract_acc_tree(user_text: str) -> str:
        """user_prompt.txt 안의 browser-use DOM 요소 블록 추출.
        browser-use 포맷: [index]<tagname attr=val />  (들여쓰기 트리 구조)
        <browser_state> ... </browser_state> 블록 통째로 저장.
        """
        start = user_text.find("<browser_state>")
        end = user_text.find("</browser_state>")
        if start != -1 and end != -1:
            return user_text[start: end + len("</browser_state>")]
        # fallback: Interactive elements 섹션만
        start = user_text.find("Interactive elements:")
        if start != -1:
            return user_text[start:]
        return "(인터랙티브 요소 없음)"

    def _save_output(self, sd: Path, result, elapsed: float) -> None:
        # result는 ChatInvokeCompletion — completion 필드에 AgentOutput
        completion = getattr(result, "completion", None)

        # llm_output.json: raw str 저장
        (sd / "llm_output.json").write_text(
            json.dumps({"raw": str(result)}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # AgentOutput 필드 추출
        eval_str = memory_str = goal_str = action_str = ""
        if completion is not None:
            eval_str   = str(getattr(completion, "evaluation_previous_goal", "") or "")
            memory_str = str(getattr(completion, "memory", "") or "")
            goal_str   = str(getattr(completion, "next_goal", "") or "")
            actions    = getattr(completion, "action", []) or []
            action_str = "\n".join(str(a) for a in actions)

        (sd / "metadata.json").write_text(
            json.dumps({
                "step": self._step,
                "elapsed_sec": elapsed,
                "status": "done",
                "evaluation_previous_goal": eval_str,
                "memory": memory_str,
                "next_goal": goal_str,
                "action": action_str,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
