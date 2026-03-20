#!/usr/bin/env python3
"""
eval_booking_run.py — WebVoyager Booking.com 태스크를 browser-use 에이전트로 실행.

결과를 WebVoyager 평가 형식(interact_messages.json + screenshot*.png)으로 저장.

Usage:
    python eval_booking_run.py                  # 랜덤 10개 실행
    python eval_booking_run.py --n 5            # 5개만
    python eval_booking_run.py --task_ids Booking--0,Booking--3  # 특정 태스크
    python eval_booking_run.py --output eval_results/my_run      # 출력 경로 지정
"""

import asyncio
import argparse
import base64
import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from browser_use import Agent, BrowserSession
from browser_use.llm import ChatOpenAI

load_dotenv()

# ── 설정 ──────────────────────────────────────────────────────────
BOOKING_DATA = Path("webvoyager_ref/data/WebVoyager_data.jsonl")
BASE_URL = "https://gateway.letsur.ai/v1"
DEFAULT_MODEL = "gemini-3-flash-preview"
MAX_STEPS = 25

AGENT_TASK_TEMPLATE = """\
Go to {url} and complete the following task:

{task}

When you have found the answer, use the `done` action and include your complete answer in the text field.
"""


# ── 데이터 로드 ───────────────────────────────────────────────────
def load_booking_tasks() -> list[dict]:
    tasks = []
    with open(BOOKING_DATA) as f:
        for line in f:
            t = json.loads(line)
            if t.get("web_name") == "Booking":
                tasks.append(t)
    return tasks


def sample_tasks(tasks: list[dict], n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    return rng.sample(tasks, min(n, len(tasks)))


# ── 아티팩트 저장 ─────────────────────────────────────────────────
def save_artifacts(task: dict, history, task_dir: Path) -> None:
    """Screenshots + interact_messages.json 저장 (WebVoyager 판정기 형식)."""

    # 1) 스크린샷 저장
    screenshots_b64 = history.screenshots(return_none_if_not_screenshot=False)
    saved_count = 0
    for i, b64 in enumerate(screenshots_b64, start=1):
        if b64:
            (task_dir / f"screenshot{i}.png").write_bytes(base64.b64decode(b64))
            saved_count += 1
    print(f"    Saved {saved_count} screenshots")

    # 2) interact_messages.json 구성
    final_answer = history.final_result() or "(no answer)"
    thoughts = history.model_thoughts()      # list[AgentBrain]
    action_names = history.action_names()    # list[str]

    messages: list[dict] = [
        {"role": "system", "content": "You are a web browsing agent."},
        {
            "role": "user",
            "content": (
                f"Now given a task: {task['ques']}  "
                f"Please interact with {task['web']} and get the answer.\n"
                "Observation: please analyze the attached screenshot and give the Thought and Action."
            ),
        },
    ]

    for thought, action in zip(thoughts, action_names):
        goal = getattr(thought, "next_goal", "") or ""
        messages.append({
            "role": "assistant",
            "content": f"Thought: {goal}\nAction: {action}",
        })

    # 판정기가 찾는 패턴: "Action: ANSWER; [<answer>]"
    messages.append({
        "role": "assistant",
        "content": f"Thought: Task completed.\nAction: ANSWER; [{final_answer}]",
    })

    with open(task_dir / "interact_messages.json", "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)


# ── 태스크 실행 ───────────────────────────────────────────────────
async def run_task(task: dict, task_dir: Path, llm) -> dict:
    task_dir.mkdir(parents=True, exist_ok=True)

    prompt = AGENT_TASK_TEMPLATE.format(url=task["web"], task=task["ques"])
    browser_session = BrowserSession(headless=False)

    agent = Agent(
        task=prompt,
        llm=llm,
        browser_session=browser_session,
        use_vision=True,
        max_actions_per_step=3,
        max_steps=MAX_STEPS,
    )

    t0 = time.time()
    history = None
    try:
        history = await agent.run()
    except Exception as e:
        print(f"    [Agent ERROR] {e}")

    elapsed = round(time.time() - t0, 1)
    final_answer = ""
    is_done = False

    if history:
        final_answer = history.final_result() or ""
        is_done = history.is_done()
        save_artifacts(task, history, task_dir)

    result = {
        "task_id": task["id"],
        "task": task["ques"],
        "url": task["web"],
        "is_done": is_done,
        "final_answer": final_answer,
        "elapsed_sec": elapsed,
        "task_dir": str(task_dir),
    }
    with open(task_dir / "result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"    Elapsed: {elapsed}s | Done: {is_done}")
    print(f"    Answer : {final_answer[:100]}")
    return result


# ── 메인 ──────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10, help="샘플링할 태스크 수")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=str, default="",
                        help="결과 저장 디렉토리 (기본: eval_results/booking_<timestamp>)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL,
                        help="에이전트 모델명")
    parser.add_argument("--task_ids", type=str, default="",
                        help="특정 태스크 ID (콤마 구분, 예: Booking--0,Booking--3)")
    args = parser.parse_args()

    api_key = os.environ.get("LETSUR_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("LETSUR_API_KEY or OPENAI_API_KEY not set in .env")

    llm = ChatOpenAI(
        model=args.model,
        api_key=api_key,
        base_url=BASE_URL,
        temperature=0,
    )

    output_dir = (
        Path(args.output)
        if args.output
        else Path("eval_results") / f"booking_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    all_tasks = load_booking_tasks()
    print(f"Loaded {len(all_tasks)} Booking.com tasks from WebVoyager dataset")

    if args.task_ids:
        ids = {t.strip() for t in args.task_ids.split(",")}
        tasks = [t for t in all_tasks if t["id"] in ids]
        print(f"Selected {len(tasks)} tasks by ID: {ids}")
    else:
        tasks = sample_tasks(all_tasks, args.n, args.seed)
        print(f"Sampled {len(tasks)} tasks (seed={args.seed})")

    print(f"Output → {output_dir}\n")

    # 선택된 태스크 목록 미리 보기
    for t in tasks:
        print(f"  {t['id']}: {t['ques'][:70]}...")
    print()

    # 태스크 실행
    all_results = []
    for i, task in enumerate(tasks, 1):
        print(f"[{i}/{len(tasks)}] {task['id']}")
        print(f"  Task: {task['ques']}")
        task_dir = output_dir / f"task{task['id']}"
        result = await run_task(task, task_dir, llm)
        all_results.append(result)
        print()

    # 요약 저장
    with open(output_dir / "run_summary.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    done_count = sum(1 for r in all_results if r["is_done"])
    print(f"{'='*60}")
    print(f"Run complete: {done_count}/{len(all_results)} tasks finished")
    print(f"Results saved → {output_dir}")
    print(f"\nNext step:")
    print(f"  python eval_booking_judge.py --result_dir {output_dir}")


if __name__ == "__main__":
    asyncio.run(main())
