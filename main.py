"""
main.py — weg-agent 진입점
사용법:
  python main.py                    # 모든 태스크 실행
  python main.py --task office_50   # 특정 태스크만
  python main.py --task gaming_100 --no-eval  # 평가 없이
  python main.py --headless         # headless 모드
"""
import asyncio
import argparse
import os
import json
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from agent import WebAgent
from tasks import TASKS, TASKS_BY_ID
from eval import evaluate, print_eval

load_dotenv()


async def run_task(task, headless: bool = False, run_eval: bool = True, explore_ui: bool = False, enforce_budget: bool = True):
    api_key = os.environ.get("LETSUR_API_KEY")
    if not api_key:
        raise RuntimeError("LETSUR_API_KEY 환경변수가 없습니다. .env 파일을 확인하세요.")

    agent = WebAgent(api_key=api_key, explore_ui=explore_ui)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--window-size=1280,900"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        # 시작 URL로 이동
        await page.goto(task.start_url, wait_until="domcontentloaded", timeout=20000)

        # 에이전트 실행
        result = await agent.run(task.prompt(), page, enforce_budget=enforce_budget)

        await browser.close()

    # 평가
    eval_result = None
    if run_eval:
        print("\n[LLM-as-Judge 평가 중...]")
        eval_result = evaluate(task, result, api_key=api_key)
        print_eval(task, eval_result)

    # 결과 저장
    _save_result(task, result, eval_result)

    return result, eval_result


def _save_result(task, result, eval_result):
    out_dir = Path("results")
    out_dir.mkdir(exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{task.id}_{ts}.json"

    data = {
        "task_id": task.id,
        "task_description": task.description,
        "budget": task.budget,
        "purpose": task.purpose,
        "success": result.success,
        "final_answer": result.final_answer,
        "steps": [
            {
                "step": s.step,
                "thought": s.thought,
                "action": s.action_raw,
                "observation": s.observation,
            }
            for s in result.steps
        ],
        "eval": eval_result,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n결과 저장: {out_path}")


async def main():
    parser = argparse.ArgumentParser(description="weg-agent: 다나와 PC 견적 에이전트")
    parser.add_argument("--task", choices=list(TASKS_BY_ID.keys()), help="특정 태스크만 실행")
    parser.add_argument("--headless", action="store_true", help="headless 모드")
    parser.add_argument("--no-eval", action="store_true", help="LLM-as-Judge 평가 생략")
    parser.add_argument("--explore-ui", action="store_true",
                        help="실행 전 다나와 UI 탐색 → knowledge/ 캐싱 (첫 실행 또는 UI 변경 시 사용)")
    parser.add_argument("--no-step-budget", action="store_true",
                        help="단계별 예산 제한 없이 실행 (가장 저렴한 제품 자동 선택)")
    args = parser.parse_args()

    tasks = [TASKS_BY_ID[args.task]] if args.task else TASKS

    for task in tasks:
        await run_task(task, headless=args.headless, run_eval=not args.no_eval,
                       explore_ui=args.explore_ui,
                       enforce_budget=not args.no_step_budget)
        print(f"\n{'─'*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
