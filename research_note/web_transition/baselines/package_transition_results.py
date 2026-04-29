#!/usr/bin/env python3
"""Package transition-memory outputs into a weg-agent-like eval_results tree."""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path

from letsur_transition_demo import SYSTEM_PROMPT, build_prompt, load_examples


def slugify(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in text)


def render_html(example_name: str, model: str, result: dict) -> str:
    rows = []
    for item in result.get("candidate_evaluations", []):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('id', '')))}</td>"
            f"<td>{html.escape(str(item.get('memory_view', '')))}</td>"
            f"<td>{html.escape(str(item.get('expected_transition', '')))}</td>"
            f"<td>{html.escape(str(item.get('failure_signal', '')))}</td>"
            f"<td>{html.escape(str(item.get('verification_rule', '')))}</td>"
            "</tr>"
        )

    table = "\n".join(rows)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{html.escape(example_name)} - {html.escape(model)}</title>
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
  <h1>{html.escape(example_name)} / {html.escape(model)}</h1>
  <p><strong>Selected action:</strong> {html.escape(str(result.get("selected_action", "")))}</p>
  <p><strong>Selection reason:</strong> {html.escape(str(result.get("selection_reason", "")))}</p>
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
      {table}
    </tbody>
  </table>
  <h2>Raw JSON</h2>
  <pre>{html.escape(json.dumps(result, ensure_ascii=False, indent=2))}</pre>
</body>
</html>
"""


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, obj: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def package_example(
    *,
    provider: str,
    model: str,
    run_id: str,
    baseline: str | None,
    example_name: str,
    source_dir: Path,
    root_dir: Path,
) -> Path:
    src = source_dir / f"{example_name}_letsur.json"
    result = json.loads(src.read_text(encoding="utf-8"))
    examples = load_examples()
    example = examples[example_name]

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
        "source_file": str(src),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json(task_dir / "metadata.json", metadata)
    write_json(task_dir / "result.json", result)
    write_json(
        task_dir / "interact_messages.json",
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(example)},
            {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)},
        ],
    )
    write_text(task_dir / "system_prompt.txt", SYSTEM_PROMPT)
    write_text(task_dir / "user_prompt.txt", build_prompt(example))
    write_text(task_dir / "assistant_output.txt", json.dumps(result, ensure_ascii=False, indent=2))
    write_text(task_dir / "viz_io.html", render_html(example_name, model, result))

    candidate_evals = result.get("candidate_evaluations", [])
    for i, candidate in enumerate(candidate_evals, start=1):
        step_dir = task_dir / f"S{i}"
        step_dir.mkdir(parents=True, exist_ok=True)
        step_metadata = {
            "step": i,
            "candidate_id": candidate.get("id"),
            "memory_view": candidate.get("memory_view"),
            "example_name": example_name,
            "model": model,
            "provider": provider,
            "baseline": baseline,
            "selected_action": result.get("selected_action"),
        }
        write_text(step_dir / "system_prompt.txt", SYSTEM_PROMPT)
        write_text(step_dir / "user_prompt.txt", build_prompt(example))
        write_json(step_dir / "metadata.json", step_metadata)
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="letsur")
    parser.add_argument("--model", default="gemini-3-flash-preview")
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--baseline", default=None)
    parser.add_argument("--source-dir", default="research_note/web_transition/baselines/output")
    parser.add_argument("--root-dir", default="eval_results")
    parser.add_argument("examples", nargs="*", default=["flight", "shopping"])
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    root_dir = Path(args.root_dir)

    for example_name in args.examples:
        package_example(
            provider=args.provider,
            model=args.model,
            run_id=args.run_id,
            baseline=args.baseline,
            example_name=example_name,
            source_dir=source_dir,
            root_dir=root_dir,
        )

    run_root = root_dir / args.provider / slugify(args.model) / args.run_id
    if args.baseline:
        run_root = run_root / slugify(args.baseline)
    print(run_root)


if __name__ == "__main__":
    main()

