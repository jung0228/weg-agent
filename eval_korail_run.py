#!/usr/bin/env python3
"""
eval_korail_run.py — 코레일 KTX 예매 태스크를 browser-use 에이전트로 실행.

WebVoyager 형식과 동일: 태스크는 자연어 ques 필드만 사용.

기본값: --dry_run (결제 직전 스크린샷 저장 후 중단)
실제 예매: --purchase 플래그 명시 필요

Usage:
    python eval_korail_run.py                        # 전체 태스크
    python eval_korail_run.py --task_ids ktx_0       # 특정 태스크
    python eval_korail_run.py --purchase             # 실제 예매 (진짜 돈!)
"""

import asyncio
import argparse
import base64
import json
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from browser_use import Agent, BrowserSession
from browser_use.llm import ChatOpenAI
from llm_logger import LoggingLLM

load_dotenv()

KORAIL_URL = "https://www.korail.com/ticket/main"
BASE_URL = "https://gateway.letsur.ai/v1"
DEFAULT_MODEL = "gemini-3-flash-preview"
MAX_STEPS = 30

# ── 태스크 정의 (WebVoyager 형식) ─────────────────────────────────
# id, ques, web — Booking.com 태스크와 동일한 구조
# 열차 종류: KTX, KTX-이음, ITX-새마을, ITX-청춘, 무궁화호 혼합
DEFAULT_TASKS = [
    # ── KTX ───────────────────────────────────────────────────────
    {
        "id": "ktx_0",
        "ques": "수원에서 대전으로 가는 2026년 4월 5일 KTX 승차권을 1명 기준으로 조회해서, 가장 빠른 열차의 출발 시각, 도착 시각, 가격을 알려주세요.",
        "web": KORAIL_URL,
    },
    {
        "id": "ktx_1",
        "ques": "수원에서 부산으로 가는 2026년 4월 10일 KTX 승차권을 1명 기준으로 조회해서, 오전 10시 이후 출발하는 열차 중 가장 저렴한 것의 열차 번호, 출발 시각, 가격을 알려주세요.",
        "web": KORAIL_URL,
    },
    {
        "id": "ktx_2",
        "ques": "서울에서 광주송정으로 가는 2026년 4월 15일 KTX 승차권을 성인 2명 기준으로 조회해서, 가장 빠른 열차의 총 금액(2인)과 출발 시각을 알려주세요.",
        "web": KORAIL_URL,
    },
    {
        "id": "ktx_3",
        "ques": "서울에서 강릉으로 가는 2026년 5월 1일 KTX-이음 승차권을 1명 기준으로 조회해서, 오후 2시 이전 출발하는 열차 목록(열차 번호, 출발 시각, 가격)을 알려주세요.",
        "web": KORAIL_URL,
    },
    # ── ITX-새마을 ─────────────────────────────────────────────────
    {
        "id": "itx_sm_0",
        "ques": "서울에서 전주로 가는 2026년 4월 8일 ITX-새마을 승차권을 1명 기준으로 조회해서, 모든 열차의 출발 시각과 가격을 나열해주세요.",
        "web": KORAIL_URL,
    },
    {
        "id": "itx_sm_1",
        "ques": "서울에서 목포로 가는 2026년 4월 20일 ITX-새마을과 KTX 승차권을 1명 기준으로 비교해서, 각각 가장 빠른 열차의 출발 시각과 가격을 알려주세요.",
        "web": KORAIL_URL,
    },
    # ── ITX-청춘 ───────────────────────────────────────────────────
    {
        "id": "itx_cc_0",
        "ques": "용산에서 춘천으로 가는 2026년 4월 12일 ITX-청춘 승차권을 1명 기준으로 조회해서, 오전 9시 이후 출발하는 열차 중 가장 빠른 것의 출발 시각, 도착 시각, 가격을 알려주세요.",
        "web": KORAIL_URL,
    },
    {
        "id": "itx_cc_1",
        "ques": "용산에서 춘천으로 가는 2026년 5월 5일(어린이날) ITX-청춘 승차권을 성인 1명, 어린이 1명 기준으로 조회해서, 오전 10시 이후 첫 열차의 출발 시각과 총 금액을 알려주세요.",
        "web": KORAIL_URL,
    },
    # ── 무궁화호 ───────────────────────────────────────────────────
    {
        "id": "mgh_0",
        "ques": "서울에서 여수EXPO로 가는 2026년 4월 18일 무궁화호 승차권을 1명 기준으로 조회해서, 가장 저렴한 열차의 출발 시각, 도착 시각, 가격을 알려주세요.",
        "web": KORAIL_URL,
    },
    {
        "id": "mgh_1",
        "ques": "청량리에서 강릉으로 가는 2026년 4월 25일 무궁화호 승차권을 1명 기준으로 조회해서, 오후 출발 열차 목록(출발 시각, 가격)을 알려주세요. KTX와 비교했을 때 가격 차이도 알려주세요.",
        "web": KORAIL_URL,
    },
    # ── 예매 태스크 (dry_run: 결제 직전 중단) ─────────────────────
    {
        "id": "book_0",
        "ques": "수원에서 부산으로 가는 2026년 4월 10일 KTX 승차권을 예매해주세요. 성인 1명, 오전 중 출발하는 가장 빠른 열차로 선택하고, 결제 직전 화면의 예매 정보(열차 번호, 출발 시각, 도착 시각, 가격)를 알려주세요.",
        "web": KORAIL_URL,
    },
    {
        "id": "book_1",
        "ques": "용산에서 춘천으로 가는 2026년 4월 12일 ITX-청춘 승차권을 예매해주세요. 성인 1명, 오전 9시 이후 첫 열차로 선택하고, 결제 직전 화면의 예매 정보(열차 번호, 출발 시각, 가격)를 알려주세요.",
        "web": KORAIL_URL,
    },
]

# ── 에이전트 프롬프트 ─────────────────────────────────────────────
DRY_RUN_PROMPT = """\
코레일 홈페이지 URL: {url}
아래 태스크를 수행해주세요.

태스크: {ques}

## 로그인 정보 (필요시)
- 회원번호: {member_id}
- 비밀번호: {password}

## 주의사항
- 팝업·광고는 닫으세요.
- **결제 버튼은 절대 누르지 마세요** (dry-run 모드).
- 결제 직전 최종 확인 화면까지만 진행하고, 그 화면의 정보를 정리해 done 액션으로 보고하세요.
- 조회 태스크라면 검색 결과를 확인하고 바로 done 액션으로 답하세요.
"""

PURCHASE_PROMPT = """\
코레일 홈페이지 URL: {url}
아래 태스크를 수행해주세요.

태스크: {ques}

## 로그인 정보 (필요시)
- 회원번호: {member_id}
- 비밀번호: {password}

## 주의사항
- 팝업·광고는 닫으세요.
- 예매 완료 후 예약번호·열차 정보·결제 금액을 정리해 done 액션으로 보고하세요.
"""


# ── 아티팩트 저장 ─────────────────────────────────────────────────
def save_artifacts(task: dict, history, task_dir: Path) -> None:
    """Screenshots + interact_messages.json 저장 (WebVoyager judge 형식)"""
    screenshots_b64 = history.screenshots(return_none_if_not_screenshot=False)
    saved = 0
    for i, b64 in enumerate(screenshots_b64, start=1):
        if b64:
            (task_dir / f"screenshot{i}.png").write_bytes(base64.b64decode(b64))
            saved += 1
    print(f"    Saved {saved} screenshots")

    final_answer = history.final_result() or "(완료 못함)"
    thoughts = history.model_thoughts()
    action_names = history.action_names()

    # WebVoyager judge가 파싱할 수 있는 형식
    messages = [
        {"role": "system", "content": "You are a web browsing agent for KTX reservation."},
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
    messages.append({
        "role": "assistant",
        "content": f"Thought: Task completed.\nAction: ANSWER; [{final_answer}]",
    })

    with open(task_dir / "interact_messages.json", "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)


# ── 태스크 실행 ───────────────────────────────────────────────────
async def run_task(task: dict, task_dir: Path, llm, dry_run: bool) -> dict:
    task_dir.mkdir(parents=True, exist_ok=True)

    member_id = os.environ.get("KORAIL_MEMBER_ID", "")
    password = os.environ.get("KORAIL_PASSWORD", "")

    template = DRY_RUN_PROMPT if dry_run else PURCHASE_PROMPT
    prompt = template.format(
        url=task["web"],
        ques=task["ques"],
        member_id=member_id,
        password=password,
    )

    logging_llm = LoggingLLM(llm, task_dir)
    browser_session = BrowserSession(headless=False)
    agent = Agent(
        task=prompt,
        llm=logging_llm,
        browser_session=browser_session,
        use_vision=True,
        max_actions_per_step=3,
        max_steps=MAX_STEPS,
    )

    print(f"    Mode: {'DRY RUN' if dry_run else '⚠️  PURCHASE'}")
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
        "ques": task["ques"],
        "web": task["web"],
        "dry_run": dry_run,
        "is_done": is_done,
        "final_answer": final_answer,
        "elapsed_sec": elapsed,
    }

    with open(task_dir / "result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"    Elapsed: {elapsed}s | Done: {is_done}")
    print(f"    Answer : {final_answer[:120]}")
    return result


# ── 메인 ─────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks_file", type=str, default="",
                        help="태스크 JSON 파일 경로 (없으면 DEFAULT_TASKS 사용)")
    parser.add_argument("--task_ids", type=str, default="",
                        help="실행할 태스크 ID (콤마 구분, 예: ktx_0,ktx_1)")
    parser.add_argument("--output", type=str, default="")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--purchase", action="store_true",
                        help="⚠️  실제 결제까지 진행")
    args = parser.parse_args()

    if args.purchase:
        print("⚠️  PURCHASE MODE: 실제 KTX 승차권이 예매됩니다!")
        print("   계속하려면 Enter, 취소하려면 Ctrl+C")
        try:
            input()
        except KeyboardInterrupt:
            print("취소됨.")
            return

    dry_run = not args.purchase

    api_key = os.environ.get("LETSUR_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("LETSUR_API_KEY not set in .env")
    if not os.environ.get("KORAIL_MEMBER_ID"):
        raise ValueError("KORAIL_MEMBER_ID not set in .env")

    llm = ChatOpenAI(
        model=args.model,
        api_key=api_key,
        base_url=BASE_URL,
        temperature=0,
    )

    if args.tasks_file:
        with open(args.tasks_file, encoding="utf-8") as f:
            tasks = json.load(f)
    else:
        tasks = DEFAULT_TASKS

    if args.task_ids:
        ids = {t.strip() for t in args.task_ids.split(",")}
        tasks = [t for t in tasks if t["id"] in ids]

    output_dir = (
        Path(args.output)
        if args.output
        else Path("eval_results") / f"korail_{'dry' if dry_run else 'real'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"KTX 평가 | {'DRY RUN' if dry_run else '실제 예매'} | {len(tasks)}개 태스크")
    print(f"Output → {output_dir}\n")
    for t in tasks:
        print(f"  {t['id']}: {t['ques'][:70]}...")
    print()

    all_results = []
    for i, task in enumerate(tasks, 1):
        print(f"[{i}/{len(tasks)}] {task['id']}")
        print(f"  {task['ques']}")
        task_dir = output_dir / f"task{task['id']}"
        result = await run_task(task, task_dir, llm, dry_run)
        all_results.append(result)
        print()

    done_count = sum(1 for r in all_results if r["is_done"])
    with open(output_dir / "run_summary.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"{'='*60}")
    print(f"완료: {done_count}/{len(all_results)}")
    print(f"결과: {output_dir}")
    if dry_run:
        print(f"\n판정:")
        print(f"  python eval_booking_judge.py --result_dir {output_dir}")


if __name__ == "__main__":
    asyncio.run(main())
