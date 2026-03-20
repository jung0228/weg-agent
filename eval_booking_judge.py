#!/usr/bin/env python3
"""
eval_booking_judge.py — eval_booking_run.py 결과를 GPT-4V로 채점.

WebVoyager 논문의 auto_eval.py 방식 그대로 사용:
- interact_messages.json에서 task & answer 추출
- 마지막 N장 스크린샷 첨부
- GPT-4V에게 'SUCCESS' / 'NOT SUCCESS' 판정 요청

Usage:
    python eval_booking_judge.py --result_dir eval_results/booking_20240101_120000
    python eval_booking_judge.py --result_dir eval_results/booking_20240101_120000 --model gpt-4o --img_num 3
"""

import argparse
import base64
import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ── WebVoyager 원본 Judge 프롬프트 (auto_eval.py와 동일) ──────────
SYSTEM_PROMPT = """As an evaluator, you will be presented with three primary components to assist you in your role:

1. Web Task Instruction: This is a clear and specific directive provided in natural language, detailing the online activity to be carried out. These requirements may include conducting searches, verifying information, comparing prices, checking availability, or any other action relevant to the specified web service (such as Amazon, Apple, ArXiv, BBC News, Booking etc).

2. Result Screenshots: This is a visual representation of the screen showing the result or intermediate state of performing a web task. It serves as visual proof of the actions taken in response to the instruction.

3. Result Response: This is a textual response obtained after the execution of the web task. It serves as textual result in response to the instruction.

-- You DO NOT NEED to interact with web pages or perform actions such as booking flights or conducting searches on websites.
-- You SHOULD NOT make assumptions based on information not presented in the screenshot when comparing it to the instructions.
-- Your primary responsibility is to conduct a thorough assessment of the web task instruction against the outcome depicted in the screenshot and in the response, evaluating whether the actions taken align with the given instructions.
-- NOTE that the instruction may involve more than one task, for example, locating the garage and summarizing the review. Failing to complete either task, such as not providing a summary, should be considered unsuccessful.
-- NOTE that the screenshot is authentic, but the response provided by LLM is generated at the end of web browsing, and there may be discrepancies between the text and the screenshots.
-- Note the difference: 1) Result response may contradict the screenshot, then the content of the screenshot prevails, 2) The content in the Result response is not mentioned on the screenshot, choose to believe the content.

You should elaborate on how you arrived at your final evaluation and then provide a definitive verdict on whether the task has been successfully accomplished, either as 'SUCCESS' or 'NOT SUCCESS'."""

USER_PROMPT = "TASK: <task>\nResult Response: <answer>\n<num> screenshots at the end: "


# ── 헬퍼 ─────────────────────────────────────────────────────────
def encode_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def judge_task_dir(
    task_dir: Path,
    client: OpenAI,
    model: str,
    img_num: int = 3,
) -> dict:
    print(f"  [{task_dir.name}]")

    # 1) interact_messages.json 로드
    msg_file = task_dir / "interact_messages.json"
    if not msg_file.exists():
        print("    ✗ interact_messages.json 없음")
        return {"verdict": None, "reason": "no interact_messages.json"}

    with open(msg_file, encoding="utf-8") as f:
        messages = json.load(f)

    if len(messages) < 2:
        return {"verdict": 0, "reason": "메시지 부족"}

    # 2) task 추출 (WebVoyager 원본과 동일한 regex)
    task_info = messages[1]["content"]
    if isinstance(task_info, list):
        task_info = next((x.get("text", "") for x in task_info if x.get("type") == "text"), "")

    m = re.search(r"Now given a task:(.+?)Please interact with", task_info, re.DOTALL)
    if not m:
        print("    ✗ task 추출 실패")
        return {"verdict": 0, "reason": "task 추출 실패"}
    task_content = m.group(1).strip()

    # 3) answer 추출 — 마지막 메시지에서 "ANSWER; [...]" 패턴
    ans_info = messages[-1]["content"]
    if isinstance(ans_info, list):
        ans_info = next((x.get("text", "") for x in ans_info if x.get("type") == "text"), "")

    if "Action: ANSWER" not in ans_info:
        print("    ✗ ANSWER 액션 없음")
        return {"verdict": 0, "reason": "ANSWER 없음"}

    m2 = re.search(r"ANSWER[; ]+\[?(.[^\]]*)\]?", ans_info)
    if not m2:
        return {"verdict": 0, "reason": "answer 파싱 실패"}
    answer_content = m2.group(1).strip()

    # 4) 스크린샷 수집 (마지막 img_num장)
    png_files = sorted(
        [
            (f, int(re.search(r"screenshot(\d+)\.png", f.name).group(1)))
            for f in task_dir.glob("screenshot*.png")
            if re.search(r"screenshot(\d+)\.png", f.name)
        ],
        key=lambda x: x[1],
    )
    end_files = png_files[-img_num:]

    if not end_files:
        print("    ✗ 스크린샷 없음")
        return {"verdict": 0, "reason": "스크린샷 없음"}

    # 5) Judge 메시지 구성
    img_content = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{encode_image(f)}"},
        }
        for f, _ in end_files
    ]

    user_text = (
        USER_PROMPT
        .replace("<task>", task_content)
        .replace("<answer>", answer_content)
        .replace("<num>", str(len(end_files)))
    )

    judge_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                *img_content,
                {"type": "text", "text": "Your verdict:\n"},
            ],
        },
    ]

    # 6) Judge API 호출 (재시도 3회)
    resp = None
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=judge_messages,
                max_tokens=1000,
                seed=42,
                temperature=0,
            )
            break
        except Exception as e:
            print(f"    Judge API 오류 (시도 {attempt+1}/3): {e}")
            time.sleep(10)

    if resp is None:
        return {"verdict": None, "reason": "Judge API 실패"}

    # 7) 판정
    judge_text = resp.choices[0].message.content
    if "NOT SUCCESS" in judge_text:
        verdict = 0
    elif "SUCCESS" in judge_text:
        verdict = 1
    else:
        verdict = None

    label = {1: "✓ SUCCESS", 0: "✗ NOT SUCCESS", None: "? UNKNOWN"}[verdict]
    print(f"    Task   : {task_content[:70]}")
    print(f"    Answer : {answer_content[:80]}")
    print(f"    Verdict: {label}")

    return {
        "task": task_content,
        "answer": answer_content,
        "verdict": verdict,
        "judge_reasoning": judge_text,
        "screenshots_used": len(end_files),
        "tokens": {
            "prompt": resp.usage.prompt_tokens,
            "completion": resp.usage.completion_tokens,
        },
    }


# ── 메인 ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--result_dir", required=True,
                        help="eval_booking_run.py가 생성한 결과 디렉토리")
    parser.add_argument("--model", default="gpt-4o",
                        help="Judge 모델 (기본: gpt-4o)")
    parser.add_argument("--api_key", default="",
                        help="OpenAI API 키 (기본: 환경변수 OPENAI_API_KEY)")
    parser.add_argument("--base_url", default="",
                        help="커스텀 base URL (letsur.ai 등)")
    parser.add_argument("--img_num", type=int, default=3,
                        help="스크린샷 첨부 수 (기본: 3)")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")

    client_kwargs: dict = {"api_key": api_key}
    if args.base_url:
        client_kwargs["base_url"] = args.base_url
    client = OpenAI(**client_kwargs)

    result_dir = Path(args.result_dir)
    task_dirs = sorted(
        [d for d in result_dir.iterdir() if d.is_dir() and d.name.startswith("task")],
        key=lambda d: d.name,
    )

    if not task_dirs:
        print(f"태스크 디렉토리가 없습니다: {result_dir}")
        return

    print(f"Judge 모델 : {args.model}")
    print(f"결과 디렉토리: {result_dir}")
    print(f"태스크 수  : {len(task_dirs)}")
    print(f"스크린샷   : 마지막 {args.img_num}장\n")

    all_judgements = []
    total_tokens = {"prompt": 0, "completion": 0}

    for task_dir in task_dirs:
        j = judge_task_dir(task_dir, client, args.model, args.img_num)
        j["task_dir"] = task_dir.name
        all_judgements.append(j)
        total_tokens["prompt"] += j.get("tokens", {}).get("prompt", 0)
        total_tokens["completion"] += j.get("tokens", {}).get("completion", 0)
        print()

    # 집계
    verdicts = [j["verdict"] for j in all_judgements]
    n_success = sum(1 for v in verdicts if v == 1)
    n_fail    = sum(1 for v in verdicts if v == 0)
    n_unknown = sum(1 for v in verdicts if v is None)
    n_total   = len(all_judgements)
    rate      = n_success / n_total if n_total else 0

    print("=" * 60)
    print(f"  SUCCESS RATE: {n_success}/{n_total}  ({rate*100:.1f}%)")
    print(f"  Success: {n_success}  |  Fail: {n_fail}  |  Unknown: {n_unknown}")
    print(f"  Judge 토큰: {total_tokens['prompt']} prompt + {total_tokens['completion']} completion")
    print("=" * 60)

    # 태스크별 결과 요약 출력
    print("\n태스크별 결과:")
    for j in all_judgements:
        label = {1: "✓", 0: "✗", None: "?"}[j["verdict"]]
        task_short = j.get("task", "")[:55]
        print(f"  {label} {j['task_dir']}: {task_short}")

    # 저장
    out = {
        "summary": {
            "total": n_total,
            "success": n_success,
            "fail": n_fail,
            "unknown": n_unknown,
            "success_rate": round(rate, 4),
            "judge_model": args.model,
            "img_num": args.img_num,
        },
        "judgements": all_judgements,
    }
    out_file = result_dir / "judge_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n결과 저장 → {out_file}")


if __name__ == "__main__":
    main()
