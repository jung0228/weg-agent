#!/usr/bin/env python3
"""Run the transition-memory demo through the Letsur OpenAI-compatible API.

Setup:

    export LETSUR_API_KEY=...
    export LETSUR_MODEL=gemini-3-flash-preview
    python3 research_note/web_transition/baselines/letsur_transition_demo.py flight

The gateway follows OpenAI chat.completions format:
    base_url=https://gateway.letsur.ai/v1
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from html import escape
from pathlib import Path

from baseline_profiles import (
    DEFAULT_BASELINE,
    baseline_choices,
    baseline_display_name,
    build_prompt_payload,
    build_system_prompt,
)

DEFAULT_BASE_URL = "https://gateway.letsur.ai/v1"
DEFAULT_MODEL = "gemini-3-flash-preview"
SYSTEM_PROMPT = build_system_prompt(DEFAULT_BASELINE)


def load_dotenv() -> None:
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_examples() -> dict:
    script_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(script_dir))
    from api_transition_demo import EXAMPLES  # type: ignore

    return EXAMPLES


def build_prompt(example: dict, baseline: str = DEFAULT_BASELINE) -> str:
    payload = build_prompt_payload(example, baseline)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def slugify(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in text)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, obj: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_html(example_name: str, model: str, result: dict, baseline: str) -> str:
    rows = []
    for item in result.get("candidate_evaluations", []):
        rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('id', '')))}</td>"
            f"<td>{escape(str(item.get('memory_view', '')))}</td>"
            f"<td>{escape(str(item.get('expected_transition', '')))}</td>"
            f"<td>{escape(str(item.get('failure_signal', '')))}</td>"
            f"<td>{escape(str(item.get('verification_rule', '')))}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{escape(example_name)} - {escape(model)} - {escape(baseline_display_name(baseline))}</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; margin: 32px; }}
    h1, h2 {{ margin: 0 0 16px; }}
    pre {{ background: #f6f8fa; padding: 16px; border-radius: 12px; overflow: auto; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top; white-space: pre-wrap; }}
    th {{ background: #fafafa; }}
  </style>
</head>
<body>
  <h1>{escape(example_name)} / {escape(model)} / {escape(baseline_display_name(baseline))}</h1>
  <p><strong>Selected action:</strong> {escape(str(result.get("selected_action", "")))}</p>
  <p><strong>Selection reason:</strong> {escape(str(result.get("selection_reason", "")))}</p>
  <h2>Candidate evaluations</h2>
  <table>
    <thead>
      <tr>
        <th>ID</th>
        <th>Memory View</th>
        <th>Expected Transition</th>
        <th>Failure Signal</th>
        <th>Verification Rule</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
  <h2>Raw JSON</h2>
  <pre>{escape(json.dumps(result, ensure_ascii=False, indent=2))}</pre>
</body>
</html>
"""


def save_run_artifacts(
    *,
    provider: str,
    model: str,
    run_id: str,
    baseline: str | None = None,
    example_name: str,
    example: dict,
    prompt: str,
    result: dict,
    system_prompt: str,
    source_file: str | None = None,
    root_dir: str | Path = "eval_results",
) -> Path:
    root_dir = Path(root_dir)
    task_root = root_dir / provider / slugify(model) / run_id
    if baseline:
        task_root = task_root / slugify(baseline)
    task_dir = task_root / f"task{example_name}_0"
    task_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "provider": provider,
        "model": model,
        "run_id": run_id,
        "baseline": baseline,
        "example_name": example_name,
        "source_file": source_file,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json(task_dir / "metadata.json", metadata)
    write_json(task_dir / "result.json", result)
    write_json(
        task_dir / "interact_messages.json",
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)},
        ],
    )
    write_text(task_dir / "system_prompt.txt", system_prompt)
    write_text(task_dir / "user_prompt.txt", prompt)
    write_text(task_dir / "assistant_output.txt", json.dumps(result, ensure_ascii=False, indent=2))
    write_text(task_dir / "viz_io.html", render_html(example_name, model, result, baseline or DEFAULT_BASELINE))

    for i, candidate in enumerate(result.get("candidate_evaluations", []), start=1):
        step_dir = task_dir / f"S{i}"
        step_dir.mkdir(parents=True, exist_ok=True)
        write_text(step_dir / "system_prompt.txt", system_prompt)
        write_text(step_dir / "user_prompt.txt", prompt)
        write_json(
            step_dir / "metadata.json",
            {
                "step": i,
                "candidate_id": candidate.get("id"),
                "memory_view": candidate.get("memory_view"),
                "example_name": example_name,
                "model": model,
                "provider": provider,
                "baseline": baseline,
                "selected_action": result.get("selected_action"),
            },
        )
        write_json(step_dir / "llm_output.json", candidate)
        write_text(
            step_dir / "acc_tree.txt",
            "\n".join(
                [
                    f"task: {example['task']}",
                    f"candidate: {candidate.get('id')}",
                    f"memory_view: {candidate.get('memory_view')}",
                    f"expected_transition: {candidate.get('expected_transition')}",
                    f"failure_signal: {candidate.get('failure_signal')}",
                    f"verification_rule: {candidate.get('verification_rule')}",
                ]
            ),
        )

    return task_dir


def main() -> None:
    import argparse

    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise SystemExit("Missing openai package. Install it with: python3 -m pip install openai") from exc

    load_dotenv()

    api_key = os.environ.get("LETSUR_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("Missing LETSUR_API_KEY")

    model = os.environ.get("LETSUR_MODEL", DEFAULT_MODEL)
    base_url = os.environ.get("LETSUR_BASE_URL", DEFAULT_BASE_URL)

    parser = argparse.ArgumentParser()
    parser.add_argument("example", nargs="?", default="flight", choices=["flight", "shopping"])
    parser.add_argument("--baseline", default=DEFAULT_BASELINE, choices=baseline_choices())
    parser.add_argument("--save-root", default="eval_results")
    parser.add_argument("--provider", default="letsur")
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    args = parser.parse_args()

    examples = load_examples()
    example_name = args.example
    if example_name not in examples:
        raise SystemExit(f"Unknown example '{example_name}'. Choose one of: {', '.join(examples)}")

    system_prompt = build_system_prompt(args.baseline)
    prompt = build_prompt(examples[example_name], baseline=args.baseline)
    client = OpenAI(base_url=base_url, api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    )
    raw_text = strip_markdown_fence(response.choices[0].message.content or "")
    print(raw_text)

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Model output was not valid JSON after stripping fences: {exc}") from exc

    save_run_artifacts(
        provider=args.provider,
        model=model,
        run_id=args.run_id,
        baseline=args.baseline,
        example_name=example_name,
        example=examples[example_name],
        prompt=prompt,
        result=result,
        system_prompt=system_prompt,
        source_file=None,
        root_dir=args.save_root,
    )


if __name__ == "__main__":
    main()

