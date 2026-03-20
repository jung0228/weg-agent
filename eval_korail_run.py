#!/usr/bin/env python3
"""
eval_korail_run.py — 코레일 KTX 예매 태스크를 browser-use 에이전트로 실행.

기본값은 --dry_run 모드: 결제 직전까지만 진행하고 스크린샷 저장 후 중단.
실제 예매는 --purchase 플래그 명시 필요.

Usage:
    # 드라이런 (결제 직전 중단) — 기본값
    python eval_korail_run.py

    # 특정 태스크만
    python eval_korail_run.py --task_ids ktx_0,ktx_1

    # 실제 예매까지 (진짜 돈 나감!)
    python eval_korail_run.py --purchase

태스크 정의:
    eval_korail_tasks.json 파일에 태스크 목록 정의
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

load_dotenv()

KORAIL_URL = "https://www.korail.com/ticket/main"
BASE_URL = "https://gateway.letsur.ai/v1"
DEFAULT_MODEL = "gemini-3-flash-preview"
MAX_STEPS = 30

# ── 태스크 정의 ──────────────────────────────────────────────────
# 각 태스크: id, 출발지, 도착지, 날짜(텍스트), 인원
DEFAULT_TASKS = [
    {
        "id": "ktx_0",
        "departure": "수원",
        "arrival": "대전",
        "date": "2026-04-05",
        "passengers": 1,
        "description": "수원 → 대전, 2026년 4월 5일, 1명",
    },
    {
        "id": "ktx_1",
        "departure": "수원",
        "arrival": "부산",
        "date": "2026-04-10",
        "passengers": 1,
        "description": "수원 → 부산, 2026년 4월 10일, 1명",
    },
    {
        "id": "ktx_2",
        "departure": "서울",
        "arrival": "광주송정",
        "date": "2026-04-15",
        "passengers": 2,
        "description": "서울 → 광주송정, 2026년 4월 15일, 2명",
    },
]

# ── 에이전트 프롬프트 ─────────────────────────────────────────────
DRY_RUN_PROMPT = """\
코레일(Korail) 홈페이지({url})에서 KTX 승차권을 예매하는 과정을 수행해주세요.

## 예매 정보
- 출발지: {departure}
- 도착지: {arrival}
- 날짜: {date}
- 인원: {passengers}명

## 단계별 지침

1. **로그인**: 우측 상단 로그인 버튼 클릭
   - 회원번호로 로그인 선택
   - 회원번호: {member_id}
   - 비밀번호: {password}

2. **승차권 검색**: 출발지·도착지·날짜 입력 후 조회

3. **열차 선택**: 가장 저렴하거나 적당한 시간대 KTX 선택

4. **좌석 선택**: 일반실 자동 배정

5. **예매 정보 확인**: 결제 직전 화면(최종 확인 페이지)에서 **반드시 멈추세요**.
   - 결제 버튼을 누르지 마세요.
   - 현재 화면을 스크린샷으로 남기고, 예매 정보(열차 번호, 출발 시각, 도착 시각, 가격)를 텍스트로 정리해 done 액션을 호출하세요.

## 중요
- 결제는 절대 진행하지 마세요 (dry_run 모드).
- 팝업·광고가 나타나면 닫으세요.
- 로그인 상태 확인 후 검색을 진행하세요.
"""

PURCHASE_PROMPT = """\
코레일(Korail) 홈페이지({url})에서 KTX 승차권을 예매해주세요.

## 예매 정보
- 출발지: {departure}
- 도착지: {arrival}
- 날짜: {date}
- 인원: {passengers}명

## 단계별 지침

1. **로그인**: 우측 상단 로그인 버튼 클릭
   - 회원번호로 로그인 선택
   - 회원번호: {member_id}
   - 비밀번호: {password}

2. **승차권 검색**: 출발지·도착지·날짜 입력 후 조회

3. **열차 선택**: 가장 빠른 시간대 KTX 선택 (오전 우선)

4. **좌석 선택**: 일반실 자동 배정

5. **결제**: 코레일페이 또는 기존 등록 결제수단으로 결제 완료

6. 예매가 완료되면 예약번호·열차 정보·가격을 정리해 done 액션으로 보고하세요.

## 중요
- 팝업·광고가 나타나면 닫으세요.
"""


# ── 헬퍼 ─────────────────────────────────────────────────────────
def save_artifacts(task: dict, history, task_dir: Path) -> None:
    """Screenshots + interact_messages.json 저장"""
    # 스크린샷 저장
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

    messages = [
        {"role": "system", "content": "You are a web browsing agent for KTX reservation."},
        {
            "role": "user",
            "content": (
                f"Now given a task: {task['description']}  "
                f"Please interact with {KORAIL_URL} and complete the task.\n"
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


async def run_task(task: dict, task_dir: Path, llm, dry_run: bool) -> dict:
    task_dir.mkdir(parents=True, exist_ok=True)

    member_id = os.environ.get("KORAIL_MEMBER_ID", "")
    password = os.environ.get("KORAIL_PASSWORD", "")

    template = DRY_RUN_PROMPT if dry_run else PURCHASE_PROMPT
    prompt = template.format(
        url=KORAIL_URL,
        departure=task["departure"],
        arrival=task["arrival"],
        date=task["date"],
        passengers=task["passengers"],
        member_id=member_id,
        password=password,
    )

    browser_session = BrowserSession(headless=False)
    agent = Agent(
        task=prompt,
        llm=llm,
        browser_session=browser_session,
        use_vision=True,
        max_actions_per_step=3,
        max_steps=MAX_STEPS,
    )

    print(f"    Mode : {'DRY RUN (결제 직전 중단)' if dry_run else '⚠️  PURCHASE MODE (실제 예매)'}")
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
        "task": task["description"],
        "departure": task["departure"],
        "arrival": task["arrival"],
        "date": task["date"],
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
                        help="태스크 JSON 파일 경로 (없으면 기본 3개 태스크 사용)")
    parser.add_argument("--task_ids", type=str, default="",
                        help="실행할 태스크 ID (콤마 구분, 예: ktx_0,ktx_1)")
    parser.add_argument("--output", type=str, default="",
                        help="결과 저장 디렉토리")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--purchase", action="store_true",
                        help="⚠️  실제 결제까지 진행 (기본값: dry_run으로 결제 직전 중단)")
    args = parser.parse_args()

    # 실제 구매 모드 경고
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

    # 태스크 로드
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

    print(f"KTX 예매 평가 시작")
    print(f"Mode   : {'DRY RUN' if dry_run else '실제 예매'}")
    print(f"태스크 : {len(tasks)}개")
    print(f"Output : {output_dir}\n")

    for t in tasks:
        print(f"  {t['id']}: {t['description']}")
    print()

    all_results = []
    for i, task in enumerate(tasks, 1):
        print(f"[{i}/{len(tasks)}] {task['id']} — {task['description']}")
        task_dir = output_dir / f"task{task['id']}"
        result = await run_task(task, task_dir, llm, dry_run)
        all_results.append(result)
        print()

    # 요약
    done_count = sum(1 for r in all_results if r["is_done"])
    with open(output_dir / "run_summary.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"{'='*60}")
    print(f"완료: {done_count}/{len(all_results)} 태스크 성공")
    print(f"결과: {output_dir}")
    if dry_run:
        print(f"\n판정하려면:")
        print(f"  python eval_booking_judge.py --result_dir {output_dir}")


if __name__ == "__main__":
    asyncio.run(main())
