#!/usr/bin/env python3
"""Compare web-transition results across multiple runs or models.

Usage:
  python3 research_note/web_transition/baselines/transition_compare.py eval_results
  python3 research_note/web_transition/baselines/transition_compare.py \
      eval_results/letsur/gemini-3-flash-preview/20260429_164258 \
      eval_results/another-provider/other-model/20260429_180000

The script groups bundles by task name and renders a single HTML dashboard that
puts the same task's model outputs side by side.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from collections import OrderedDict
from pathlib import Path
from typing import Any

from transition_viewer import (
    CSS,
    chip,
    chips,
    discover_task_dirs,
    esc,
    first_line,
    load_task_bundle,
    render_candidate_cards,
    render_memory_cards,
    render_observation,
    render_step_cards,
)


def load_bundles_from_path(path: Path) -> list[dict[str, Any]]:
    if (path / "result.json").exists():
        return [load_task_bundle(path)]
    return [load_task_bundle(task_dir) for task_dir in discover_task_dirs(path)]


def source_label(bundle: dict[str, Any]) -> str:
    metadata = bundle.get("metadata", {})
    parts = [
        metadata.get("provider"),
        metadata.get("model"),
        metadata.get("run_id"),
        metadata.get("baseline") or "default",
    ]
    return " / ".join(str(part) for part in parts if part)


def group_bundles(paths: list[Path]) -> list[dict[str, Any]]:
    groups: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for source_order, root in enumerate(paths):
        for bundle in load_bundles_from_path(root):
            task_name = str(
                bundle.get("task_name")
                or bundle.get("payload", {}).get("task")
                or bundle.get("metadata", {}).get("example_name")
                or Path(bundle.get("task_dir", root)).name
            )
            group = groups.setdefault(
                task_name,
                {
                    "task_name": task_name,
                    "payload": bundle.get("payload", {}),
                    "bundles": [],
                },
            )
            group["bundles"].append(
                {
                    **bundle,
                    "source_root": str(root),
                    "source_label": source_label(bundle),
                    "source_order": source_order,
                }
            )
    return list(groups.values())


def render_shared_input(bundle: dict[str, Any]) -> str:
    payload = bundle.get("payload", {})
    return f"""
      <section class="panel shared-input">
        <div class="section-label">Shared Input</div>
        {render_observation(payload)}
        <div style="height:12px"></div>
        <div class="card">
          <div class="card-title">
            <h3>Candidate Actions</h3>
            <span class="meta">{len(payload.get("candidate_actions", []) or [])} actions</span>
          </div>
          {render_candidate_cards(payload)}
        </div>
        <div style="height:12px"></div>
        <div class="card">
          <div class="card-title">
            <h3>Retrieved Transition Memory</h3>
            <span class="meta">{len(payload.get("retrieved_transition_memory", []) or [])} items</span>
          </div>
          {render_memory_cards(payload)}
        </div>
      </section>
    """


def render_model_card(bundle: dict[str, Any], compare_root: Path) -> str:
    metadata = bundle.get("metadata", {})
    result = bundle.get("result", {})
    task_dir = Path(bundle.get("task_dir", ""))
    selected_action = result.get("selected_action", "—")
    candidate_count = len(result.get("candidate_evaluations", []) or [])
    memory_count = len(bundle.get("payload", {}).get("retrieved_transition_memory", []) or [])
    try:
        rel_html = os.path.relpath(task_dir / "viz_io.html", start=compare_root)
        rel_result = os.path.relpath(task_dir / "result.json", start=compare_root)
    except ValueError:
        rel_html = str(task_dir / "viz_io.html")
        rel_result = str(task_dir / "result.json")

    return f"""
      <article class="model-card">
        <div class="card-title">
          <h3>{esc(bundle.get("source_label", metadata.get("model", "Model")))}</h3>
          <span class="meta">{esc(selected_action)}</span>
        </div>
        <div class="chips" style="margin-bottom:10px">
          {chip(metadata.get("provider", ""), "gray")}
          {chip(metadata.get("model", ""), "indigo")}
          {chip(metadata.get("baseline", "") or "default", "teal")}
        </div>
        <div class="small"><b>Run:</b> {esc(metadata.get("run_id", ""))}</div>
        <div class="small"><b>Source:</b> {esc(bundle.get("source_root", ""))}</div>
        <div class="small" style="margin-top:8px; line-height:1.7"><b>Reason:</b> {esc(first_line(result.get("selection_reason", ""), 180))}</div>
        <div class="metric-row compact">
          <div class="metric"><div class="value">{candidate_count}</div><div class="label">candidates</div></div>
          <div class="metric"><div class="value">{memory_count}</div><div class="label">memory items</div></div>
        </div>
        <div class="stack" style="margin-top:12px">
          {render_step_cards(bundle)}
        </div>
        <div class="links" style="margin-top:12px">
          <a class="button-link" href="{esc(rel_html)}">Open task page</a>
          <a class="button-link secondary" href="{esc(rel_result)}">Raw JSON</a>
        </div>
      </article>
    """


def render_task_section(group: dict[str, Any], compare_root: Path) -> str:
    bundles = group.get("bundles", [])
    if not bundles:
        return ""
    bundles = sorted(bundles, key=lambda b: (b.get("source_order", 0), b.get("source_label", "")))
    shared_bundle = bundles[0]
    input_panel = render_shared_input(shared_bundle)
    model_cards = "".join(render_model_card(bundle, compare_root) for bundle in bundles)
    source_labels = sorted({str(bundle.get("source_label", "")) for bundle in bundles if bundle.get("source_label")})
    return f"""
      <section class="task-section">
        <div class="task-head">
          <div>
            <div class="section-label">Task</div>
            <h2>{esc(group.get("task_name", "Task"))}</h2>
            <div class="small">{esc(first_line(shared_bundle.get("result", {}).get("selection_reason", "") or shared_bundle.get("payload", {}).get("task", "")))}</div>
          </div>
          <div class="chips">
            {''.join(chip(label, "gray") for label in source_labels)}
          </div>
        </div>
        <div class="compare-layout">
          {input_panel}
          <div class="model-strip">
            {model_cards}
          </div>
        </div>
      </section>
    """


def render_compare_page(compare_root: Path, groups: list[dict[str, Any]]) -> str:
    bundle_total = sum(len(group.get("bundles", [])) for group in groups)
    source_labels = sorted(
        {
            str(bundle.get("source_label", ""))
            for group in groups
            for bundle in group.get("bundles", [])
            if bundle.get("source_label")
        }
    )
    task_names = [group.get("task_name", "Task") for group in groups]

    nav_links = "".join(
        f'<a class="chip indigo" href="#task-{esc(str(index))}">{esc(name)}</a>'
        for index, name in enumerate(task_names, start=1)
    )
    sections = []
    for index, group in enumerate(groups, start=1):
        section_html = render_task_section(group, compare_root)
        if section_html:
            sections.append(section_html.replace('<section class="task-section">', f'<section class="task-section" id="task-{index}">', 1))

    return f"""<!doctype html>
<html lang="ko">
<head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>{esc(compare_root.name)} · Web Transition Compare</title>
  <style>{CSS}
{COMPARE_CSS}</style>
</head>
<body>
  <div class="page">
    <header class="hero">
      <div>
        <div class="kicker">Web Transition Compare</div>
        <h1>{esc(compare_root.name)}</h1>
        <p>{esc("같은 task를 여러 run/model에서 나란히 비교하는 페이지입니다.")}</p>
        <div class="metric-row">
          <div class="metric"><div class="value">{len(groups)}</div><div class="label">tasks</div></div>
          <div class="metric"><div class="value">{bundle_total}</div><div class="label">result bundles</div></div>
          <div class="metric"><div class="value">{len(source_labels) or 1}</div><div class="label">sources</div></div>
          <div class="metric"><div class="value">{sum(1 for g in groups if len(g.get("bundles", [])) > 1)}</div><div class="label">multi-model groups</div></div>
        </div>
      </div>
      <div style="min-width:280px;max-width:420px">
        <div class="metric-row" style="margin-top:0">
          <div class="metric" style="flex:1 1 100%">
            <div class="label">Sources</div>
            <div class="small" style="color:#e2e8f0;line-height:1.7">{esc(", ".join(source_labels) or "default")}</div>
          </div>
          <div class="metric" style="flex:1 1 100%">
            <div class="label">Root</div>
            <div class="small" style="color:#e2e8f0;line-height:1.7">{esc(str(compare_root))}</div>
          </div>
        </div>
      </div>
    </header>

    <nav class="nav">
      {nav_links}
    </nav>

    <div class="stack">
      {''.join(sections)}
    </div>
  </div>
</body>
</html>
"""


COMPARE_CSS = """
:root {
  --bg: #f7f3ea;
  --bg2: #eef2ff;
  --panel: rgba(255, 255, 255, 0.88);
  --panel-strong: rgba(255, 255, 255, 0.98);
  --line: rgba(15, 23, 42, 0.11);
  --text: #10203a;
  --muted: #63708a;
  --accent: #0f766e;
  --accent-2: #4338ca;
  --accent-3: #b45309;
  --shadow: 0 20px 55px rgba(15, 23, 42, 0.10);
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  color: var(--text);
  background:
    radial-gradient(circle at top left, rgba(255, 246, 205, 0.7), transparent 28%),
    radial-gradient(circle at top right, rgba(199, 210, 254, 0.55), transparent 26%),
    linear-gradient(180deg, var(--bg), var(--bg2));
  font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.page {
  max-width: 1680px;
  margin: 0 auto;
  padding: 24px;
}

.hero {
  border-radius: 28px;
  padding: 24px;
  color: white;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 56%, #0f766e 120%);
  box-shadow: 0 24px 68px rgba(15, 23, 42, 0.25);
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: flex-start;
}

.hero h1 {
  margin: 8px 0 10px;
  font-size: clamp(28px, 3vw, 44px);
  line-height: 1.03;
  letter-spacing: -0.04em;
}

.hero p {
  margin: 0;
  max-width: 78ch;
  color: #dbeafe;
  line-height: 1.65;
}

.kicker {
  text-transform: uppercase;
  letter-spacing: 0.18em;
  font-size: 11px;
  color: #a5f3fc;
  font-weight: 800;
}

.metric-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 16px;
}

.metric {
  min-width: 120px;
  padding: 12px 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.10);
  border: 1px solid rgba(255, 255, 255, 0.16);
  backdrop-filter: blur(10px);
}

.metric .value {
  font-size: 19px;
  font-weight: 800;
  line-height: 1.15;
  overflow-wrap: anywhere;
}

.metric .label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: rgba(255, 255, 255, 0.76);
  margin-top: 4px;
}

.stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 18px;
}

.nav {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 16px;
}

.panel, .model-card, .task-section {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 24px;
  padding: 18px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(12px);
}

.task-section {
  background: var(--panel-strong);
}

.task-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.task-head h2 {
  margin: 6px 0 6px;
  font-size: clamp(22px, 2vw, 32px);
  line-height: 1.1;
  letter-spacing: -0.03em;
}

.section-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 12px;
}

.compare-layout {
  display: grid;
  grid-template-columns: minmax(320px, 0.95fr) minmax(420px, 1.6fr);
  gap: 16px;
  margin-top: 16px;
  align-items: start;
}

.model-strip {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(360px, 1fr);
  gap: 14px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.shared-input {
  align-self: start;
}

.model-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 100%;
}

.model-card .links {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.chip {
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
  border-radius: 999px;
  background: #e2e8f0;
  color: #0f172a;
  font-size: 12px;
  font-weight: 800;
  text-decoration: none;
}

.chip.gray { background: #e2e8f0; color: #0f172a; }
.chip.indigo { background: #e0e7ff; color: #3730a3; }
.chip.teal { background: #d1fae5; color: #065f46; }

.card {
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.78);
  padding: 14px;
}

.card.mini {
  padding: 12px;
}

.card + .card {
  margin-top: 12px;
}

.card-title {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: flex-start;
  margin-bottom: 10px;
}

.card-title h3 {
  margin: 0;
  font-size: 16px;
  line-height: 1.15;
}

.meta {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--muted);
  white-space: nowrap;
}

.small {
  color: #334155;
  font-size: 13px;
  line-height: 1.55;
}

.stack-inner {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.button-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 999px;
  text-decoration: none;
  font-weight: 800;
  background: #0f172a;
  color: white;
  font-size: 12px;
}

.button-link.secondary {
  background: #e2e8f0;
  color: #0f172a;
}

details {
  margin-top: 10px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: rgba(255,255,255,.70);
  padding: 10px 12px;
}

details summary {
  cursor: pointer;
  font-weight: 800;
}

pre {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.6;
  margin-top: 10px;
  color: #0f172a;
}

@media (max-width: 1180px) {
  .compare-layout { grid-template-columns: 1fr; }
  .hero { flex-direction: column; }
  .model-strip { grid-auto-flow: row; grid-auto-columns: 1fr; }
}
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", default=["eval_results"])
    parser.add_argument("--open", action="store_true", help="Open the generated HTML in the system browser")
    args = parser.parse_args()

    input_paths = [Path(path) for path in args.paths]
    groups = group_bundles(input_paths)
    if not groups:
        raise SystemExit(f"No task result folders found under: {', '.join(str(p) for p in input_paths)}")

    compare_root = Path(os.path.commonpath([str(path.resolve()) for path in input_paths]))
    out = compare_root / "comparison_viewer.html"
    out.write_text(render_compare_page(compare_root, groups), encoding="utf-8")
    print(out)
    if args.open:
        subprocess.run(["open", str(out)], check=False)


if __name__ == "__main__":
    main()
