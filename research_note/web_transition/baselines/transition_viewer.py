#!/usr/bin/env python3
"""Render rich HTML pages for web-transition results.

Usage:
  python3 research_note/web_transition/baselines/transition_viewer.py <task-or-run-path>

Examples:
  python3 research_note/web_transition/baselines/transition_viewer.py eval_results/letsur/gemini-3-flash-preview/20260429_164258
  python3 research_note/web_transition/baselines/transition_viewer.py eval_results/letsur/gemini-3-flash-preview/20260429_164258/taskflight_0

If you pass a run directory, the script regenerates every task's `viz_io.html`
and also writes a `transition_viewer.html` index for the run.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
from pathlib import Path
from typing import Any


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_text(path: Path, default: str = "") -> str:
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8")


def parse_user_payload(interact_messages: Any) -> dict[str, Any]:
    if not isinstance(interact_messages, list):
        return {}
    for message in interact_messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, dict):
            return content
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                return {"raw_user_prompt": content}
            if isinstance(parsed, dict):
                return parsed
            return {"raw_user_prompt": content}
    return {}


def load_task_bundle(task_dir: Path) -> dict[str, Any]:
    metadata = load_json(task_dir / "metadata.json", {})
    result = load_json(task_dir / "result.json", {})
    payload = parse_user_payload(load_json(task_dir / "interact_messages.json", []))
    task_name = (
        metadata.get("example_name")
        or payload.get("task")
        or result.get("task")
        or task_dir.name
    )
    return {
        "task_dir": task_dir,
        "task_name": task_name,
        "metadata": metadata,
        "result": result,
        "payload": payload,
        "system_prompt": load_text(task_dir / "system_prompt.txt"),
        "user_prompt": load_text(task_dir / "user_prompt.txt"),
        "assistant_output": load_text(task_dir / "assistant_output.txt"),
    }


def discover_task_dirs(root: Path) -> list[Path]:
    if (root / "result.json").exists():
        return [root]

    direct = [
        d
        for d in root.iterdir()
        if d.is_dir() and d.name.startswith("task") and (d / "result.json").exists()
    ]
    if direct:
        return sorted(direct, key=lambda p: p.name)

    nested = [
        p
        for p in root.rglob("task*_0")
        if p.is_dir() and (p / "result.json").exists()
    ]
    return sorted(nested, key=lambda p: (str(p.parent), p.name))


def first_line(text: str, limit: int = 140) -> str:
    clean = " ".join((text or "").strip().split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def chip(text: Any, tone: str = "gray") -> str:
    return f'<span class="chip {tone}">{esc(text)}</span>'


def chips(items: list[Any], tone: str = "gray") -> str:
    if not items:
        return '<div class="small">-</div>'
    return '<div class="chips">' + "".join(chip(item, tone=tone) for item in items) + "</div>"


def keyval(label: str, value: Any) -> str:
    return f"""
      <div class="key">{esc(label)}</div>
      <div class="value">{value}</div>
    """


def render_observation(payload: dict[str, Any]) -> str:
    obs = payload.get("observation", {})
    if not isinstance(obs, dict):
        obs = {}
    salient_elements = obs.get("salient_elements", [])
    if not isinstance(salient_elements, list):
        salient_elements = []

    element_cards = []
    for element in salient_elements:
        if not isinstance(element, dict):
            continue
        element_cards.append(
            f"""
            <div class="card mini">
              <div class="card-title">
                <h4>{esc(element.get("id", "element"))}</h4>
                <span class="meta">{esc(element.get("role", ""))}</span>
              </div>
              <div class="small"><b>Text:</b> {esc(element.get("text", ""))}</div>
              <div class="small"><b>Region:</b> {esc(element.get("region", ""))}</div>
              <div class="small"><b>Context:</b> {esc(element.get("context", ""))}</div>
            </div>
            """
        )

    visible_regions = obs.get("visible_regions", [])
    if not isinstance(visible_regions, list):
        visible_regions = []

    return f"""
      <div class="card">
        <div class="card-title">
          <h3>Observation</h3>
          <span class="meta">{esc(obs.get("page_type", "—"))}</span>
        </div>
        <div class="small" style="margin-bottom:8px"><b>Task:</b> {esc(payload.get("task", "—"))}</div>
        <div class="small" style="margin-bottom:8px"><b>Visible regions:</b></div>
        {chips(visible_regions, tone="indigo")}
        <div style="height:12px"></div>
        <div class="small" style="margin-bottom:8px"><b>Salient elements:</b></div>
        <div class="stack">
          {"".join(element_cards) if element_cards else '<div class="small">-</div>'}
        </div>
      </div>
    """


def render_memory_cards(payload: dict[str, Any]) -> str:
    memories = payload.get("retrieved_transition_memory", [])
    if not isinstance(memories, list) or not memories:
        return '<div class="small">No retrieved memory was provided.</div>'

    cards = []
    for i, memory in enumerate(memories, start=1):
        if not isinstance(memory, dict):
            continue
        cards.append(
            f"""
            <div class="card mini">
              <div class="card-title">
                <h4>{esc(memory.get("action_affordance", f"memory_{i}"))}</h4>
                <span class="meta">{esc(memory.get("page_state", ""))}</span>
              </div>
              <div class="small"><b>Expected:</b> {esc(memory.get("expected_transition", ""))}</div>
              <div class="small"><b>Failure:</b> {esc(memory.get("failure_signal", ""))}</div>
              <div class="small"><b>Verify:</b> {esc(memory.get("verification_rule", ""))}</div>
            </div>
            """
        )
    return "".join(cards)


def render_candidate_cards(payload: dict[str, Any]) -> str:
    candidate_actions = payload.get("candidate_actions", [])
    if not isinstance(candidate_actions, list) or not candidate_actions:
        return '<div class="small">No candidate actions.</div>'

    cards = []
    for action in candidate_actions:
        if not isinstance(action, dict):
            continue
        cards.append(
            f"""
            <div class="card mini">
              <div class="card-title">
                <h4>{esc(action.get("id", "candidate"))} · {esc(action.get("surface", ""))}</h4>
                <span class="meta">{esc(action.get("op", ""))}</span>
              </div>
              <div class="small"><b>Target:</b> {esc(action.get("target", ""))}</div>
              <div class="small"><b>Surface:</b> {esc(action.get("surface", ""))}</div>
            </div>
            """
        )
    return "".join(cards)


def render_step_cards(bundle: dict[str, Any]) -> str:
    payload = bundle.get("payload", {})
    result = bundle.get("result", {})
    candidate_actions = payload.get("candidate_actions", [])
    if not isinstance(candidate_actions, list):
        candidate_actions = []
    candidate_by_id = {
        str(action.get("id", "")): action
        for action in candidate_actions
        if isinstance(action, dict)
    }
    evaluations = result.get("candidate_evaluations", [])
    if not isinstance(evaluations, list):
        evaluations = []
    evaluation_by_id = {
        str(item.get("id", "")): item
        for item in evaluations
        if isinstance(item, dict)
    }
    memories = payload.get("retrieved_transition_memory", [])
    if not isinstance(memories, list):
        memories = []
    observation = payload.get("observation", {})
    if not isinstance(observation, dict):
        observation = {}
    salient_by_id = {
        str(element.get("id", "")): element
        for element in observation.get("salient_elements", []) or []
        if isinstance(element, dict)
    }

    step_cards = []
    for idx, action in enumerate(candidate_actions, start=1):
        if not isinstance(action, dict):
            continue
        candidate_id = str(action.get("id", ""))
        evaluation = evaluation_by_id.get(candidate_id, {})
        selected = result.get("selected_action") == candidate_id
        salient = salient_by_id.get(str(action.get("target", "")), {})
        support_memory = None
        if selected:
            support_memory = memories[0] if memories else None

        step_cards.append(
            f"""
            <article class="step-card {'selected' if selected else ''}" id="step-{esc(candidate_id)}">
              <div class="step-head">
                <div>
                  <div class="step-id">Step {idx}</div>
                  <div class="step-title">{esc(candidate_id)} · {esc(action.get("surface", ""))}</div>
                </div>
                {"<span class='chip teal'>Selected</span>" if selected else ""}
              </div>
              <div class="step-grid">
                <div class="subpanel">
                  <div class="sublabel">Input</div>
                  <div class="small"><b>Operation:</b> {esc(action.get("op", ""))}</div>
                  <div class="small"><b>Target:</b> {esc(action.get("target", ""))}</div>
                  <div class="small"><b>Surface:</b> {esc(action.get("surface", ""))}</div>
                  {(
                      "<div class='card mini' style='margin-top:10px'>"
                      "<div class='card-title'><h4>Matched element</h4><span class='meta'>"
                      + esc(salient.get("id", ""))
                      + "</span></div>"
                      + "<div class='small'><b>Role:</b> "
                      + esc(salient.get("role", ""))
                      + "</div><div class='small'><b>Text:</b> "
                      + esc(salient.get("text", ""))
                      + "</div><div class='small'><b>Region:</b> "
                      + esc(salient.get("region", ""))
                      + "</div><div class='small'><b>Context:</b> "
                      + esc(salient.get("context", ""))
                      + "</div></div>"
                  ) if salient else "<div class='small' style='margin-top:10px'>No matched element in observation.</div>"}
                </div>
                <div class="subpanel">
                  <div class="sublabel">Output</div>
                  <div class="small"><b>Expected transition:</b> {esc(evaluation.get("expected_transition", "—"))}</div>
                  <div class="small"><b>Failure signal:</b> {esc(evaluation.get("failure_signal", "—"))}</div>
                  <div class="small"><b>Verification rule:</b> {esc(evaluation.get("verification_rule", "—"))}</div>
                  <div class="small" style="margin-top:8px"><b>Memory view:</b> {esc(evaluation.get("memory_view", "—"))}</div>
                  {(
                      "<div class='card mini' style='margin-top:10px'>"
                      "<div class='card-title'><h4>Support memory</h4><span class='meta'>"
                      + esc(support_memory.get("action_affordance", ""))
                      + "</span></div>"
                      + "<div class='small'><b>Expected:</b> "
                      + esc(support_memory.get("expected_transition", ""))
                      + "</div><div class='small'><b>Failure:</b> "
                      + esc(support_memory.get("failure_signal", ""))
                      + "</div><div class='small'><b>Verify:</b> "
                      + esc(support_memory.get("verification_rule", ""))
                      + "</div></div>"
                  ) if support_memory else ""}
                </div>
              </div>
              <details>
                <summary>Raw candidate JSON</summary>
                <pre>{esc(json.dumps({"action": action, "evaluation": evaluation}, ensure_ascii=False, indent=2))}</pre>
              </details>
            </article>
            """
        )
    return "".join(step_cards)


def render_raw_panel(bundle: dict[str, Any]) -> str:
    metadata = bundle.get("metadata", {})
    result = bundle.get("result", {})
    return f"""
      <div class="card" style="margin-bottom:12px">
        <div class="card-title">
          <h3>Selection</h3>
          <span class="meta">{esc(result.get("selected_action", "—"))}</span>
        </div>
        <div class="small" style="line-height:1.7">{esc(result.get("selection_reason", "—"))}</div>
      </div>

      <details open>
        <summary>Prompt packet</summary>
        <pre>{esc(bundle.get("user_prompt", ""))}</pre>
      </details>

      <details>
        <summary>System prompt</summary>
        <pre>{esc(bundle.get("system_prompt", ""))}</pre>
      </details>

      <details>
        <summary>Assistant output</summary>
        <pre>{esc(bundle.get("assistant_output", ""))}</pre>
      </details>

      <details>
        <summary>Metadata</summary>
        <pre>{esc(json.dumps(metadata, ensure_ascii=False, indent=2))}</pre>
      </details>
    """


CSS = """
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
  max-width: 1560px;
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
  min-width: 0;
  overflow-wrap: anywhere;
}

.metric .label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: rgba(255, 255, 255, 0.76);
  margin-top: 4px;
}

.layout {
  display: grid;
  grid-template-columns: minmax(320px, 1fr) minmax(360px, 1.35fr) minmax(280px, 0.88fr);
  gap: 16px;
  margin-top: 16px;
  align-items: start;
}

.index-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
  gap: 14px;
  margin-top: 18px;
}

.panel, .index-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 24px;
  padding: 18px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(12px);
}

.index-card {
  background: var(--panel-strong);
}

.section-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 12px;
}

.stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
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
.chip.orange { background: #ffedd5; color: #9a3412; }

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
  gap: 10px;
  align-items: flex-start;
  margin-bottom: 10px;
}

.card-title h3, .card-title h4 {
  margin: 0;
  font-size: 15px;
  line-height: 1.3;
}

.card-title .meta {
  font-size: 12px;
  color: var(--muted);
  white-space: nowrap;
}

.small {
  font-size: 12px;
  line-height: 1.65;
  color: #334155;
}

.keyval {
  display: grid;
  grid-template-columns: 128px 1fr;
  gap: 8px 12px;
  font-size: 13px;
  line-height: 1.55;
}

.key {
  color: var(--muted);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 800;
  padding-top: 2px;
}

.value {
  min-width: 0;
  overflow-wrap: anywhere;
}

.links {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.button-link {
  display: inline-flex;
  align-items: center;
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

.step-card {
  position: relative;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: linear-gradient(180deg, rgba(255,255,255,.96), rgba(248,250,252,.92));
  padding: 14px;
  overflow: hidden;
}

.step-card.selected {
  border-color: rgba(13, 148, 136, 0.55);
  box-shadow: 0 14px 30px rgba(13, 148, 136, 0.12);
}

.step-card::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: linear-gradient(180deg, #14b8a6, #3b82f6);
}

.step-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
  margin-bottom: 10px;
}

.step-id {
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--muted);
}

.step-title {
  font-weight: 900;
  font-size: 14px;
  margin-top: 2px;
}

.step-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.subpanel {
  border-radius: 14px;
  border: 1px solid var(--line);
  background: #fff;
  padding: 12px;
}

.sublabel {
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--muted);
  margin-bottom: 8px;
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

a.chip:hover, .button-link:hover {
  filter: brightness(1.03);
}

@media (max-width: 1180px) {
  .layout { grid-template-columns: 1fr; }
  .step-grid { grid-template-columns: 1fr; }
  .hero { flex-direction: column; }
}
"""


def write_html(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def render_task_page(bundle: dict[str, Any]) -> str:
    payload = bundle.get("payload", {})
    result = bundle.get("result", {})
    metadata = bundle.get("metadata", {})
    observation = payload.get("observation", {})
    if not isinstance(observation, dict):
        observation = {}
    task_name = bundle.get("task_name") or payload.get("task") or result.get("task") or "Task"
    provider = bundle.get("metadata", {}).get("provider", "")
    model = bundle.get("metadata", {}).get("model", "")
    baseline = bundle.get("metadata", {}).get("baseline", "")
    run_id = bundle.get("metadata", {}).get("run_id", "")
    candidate_count = len(result.get("candidate_evaluations", []) or [])
    memory_count = len(payload.get("retrieved_transition_memory", []) or [])
    selected_action = result.get("selected_action", "—")
    page_type = observation.get("page_type", "—")
    context_line = " / ".join([x for x in [provider, model, baseline, run_id] if x]) or "—"
    subtitle = first_line(result.get("selection_reason", "") or payload.get("task", ""))
    prompt_packet = bundle.get("user_prompt", "")
    system_prompt = bundle.get("system_prompt", "")
    assistant_output = bundle.get("assistant_output", "")

    input_panel = f"""
      <section class="panel">
        <div class="section-label">Input Packet</div>
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
            <span class="meta">{memory_count} items</span>
          </div>
          {render_memory_cards(payload)}
        </div>
      </section>
    """

    step_links = []
    for action in payload.get("candidate_actions", []) or []:
        if not isinstance(action, dict):
            continue
        step_links.append(f'<a class="chip indigo" href="#step-{esc(action.get("id", ""))}">{esc(action.get("id", ""))}</a>')

    step_panel = f"""
      <section class="panel">
        <div class="section-label">Step-by-Step Output</div>
        <div class="chips" style="margin-bottom:12px">
          {''.join(step_links)}
        </div>
        <div class="stack">
          {render_step_cards(bundle)}
        </div>
      </section>
    """

    raw_panel = f"""
      <aside class="panel">
        <div class="section-label">Selection / Raw</div>
        <div class="card" style="margin-bottom:12px">
          <div class="card-title">
            <h3>Selection</h3>
            <span class="meta">{esc(selected_action)}</span>
          </div>
          <div class="small" style="line-height:1.7">{esc(result.get("selection_reason", "—"))}</div>
        </div>

        <details open>
          <summary>Prompt packet</summary>
          <pre>{esc(prompt_packet)}</pre>
        </details>

        <details>
          <summary>System prompt</summary>
          <pre>{esc(system_prompt)}</pre>
        </details>

        <details>
          <summary>Assistant output</summary>
          <pre>{esc(assistant_output)}</pre>
        </details>

        <details>
          <summary>Metadata</summary>
          <pre>{esc(json.dumps(metadata, ensure_ascii=False, indent=2))}</pre>
        </details>
      </aside>
    """

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(task_name)} · Transition Viewer</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="page">
    <header class="hero">
      <div>
        <div class="kicker">Web Transition Viewer</div>
        <h1>{esc(task_name)}</h1>
        <p>{esc(subtitle)}</p>
        <div class="metric-row">
          <div class="metric"><div class="value">{candidate_count}</div><div class="label">candidates</div></div>
          <div class="metric"><div class="value">{memory_count}</div><div class="label">memory items</div></div>
          <div class="metric"><div class="value">{esc(selected_action)}</div><div class="label">selected action</div></div>
          <div class="metric"><div class="value">{esc(page_type)}</div><div class="label">page type</div></div>
        </div>
      </div>
      <div style="min-width:280px;max-width:380px">
        <div class="metric-row" style="margin-top:0">
          <div class="metric" style="flex:1 1 100%">
            <div class="label">Context</div>
            <div class="small" style="color:#e2e8f0;line-height:1.7">{esc(context_line)}</div>
          </div>
          <div class="metric" style="flex:1 1 100%">
            <div class="label">Task dir</div>
            <div class="small" style="color:#e2e8f0;line-height:1.7">{esc(bundle.get("task_dir", ""))}</div>
          </div>
        </div>
      </div>
    </header>

    <div class="layout">
      {input_panel}
      {step_panel}
      {raw_panel}
    </div>
  </div>
</body>
</html>
"""


def render_run_index_page(run_root: Path, bundles: list[dict[str, Any]]) -> str:
    total = len(bundles)
    selected = sum(1 for bundle in bundles if (bundle.get("result") or {}).get("selected_action"))
    candidate_total = sum(
        len((bundle.get("result") or {}).get("candidate_evaluations", []) or [])
        for bundle in bundles
    )
    baseline_names = sorted(
        {
            str(bundle.get("metadata", {}).get("baseline", ""))
            for bundle in bundles
            if bundle.get("metadata", {}).get("baseline")
        }
    )

    cards = []
    for bundle in bundles:
        result = bundle.get("result", {})
        payload = bundle.get("payload", {})
        task_dir = Path(bundle.get("task_dir", ""))
        try:
            rel_html = os.path.relpath(task_dir / "viz_io.html", start=run_root)
            rel_result = os.path.relpath(task_dir / "result.json", start=run_root)
        except ValueError:
            rel_html = str(task_dir / "viz_io.html")
            rel_result = str(task_dir / "result.json")
        cards.append(
            f"""
            <article class="index-card">
              <div class="card-title">
                <h3>{esc(bundle.get("task_name", "Task"))}</h3>
                <span class="meta">{esc(result.get("selected_action", "—"))}</span>
              </div>
              <div class="small" style="margin-bottom:10px">{esc(first_line(result.get("selection_reason", "") or payload.get("task", "")))}</div>
              <div class="chips" style="margin-bottom:10px">
                {chip(bundle.get("metadata", {}).get("provider", ""), "gray")}
                {chip(bundle.get("metadata", {}).get("model", ""), "indigo")}
                {chip(bundle.get("metadata", {}).get("baseline", "") or "default", "teal")}
              </div>
              <div class="keyval">
                {keyval("Candidates", len(result.get("candidate_evaluations", []) or []))}
                {keyval("Memory items", len((payload.get("retrieved_transition_memory", []) or [])))}
                {keyval("Task dir", f'<code>{esc(str(task_dir))}</code>')}
              </div>
              <div class="links">
                <a class="button-link" href="{esc(rel_html)}">Open task page</a>
                <a class="button-link secondary" href="{esc(rel_result)}">Raw JSON</a>
              </div>
            </article>
            """
        )

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(run_root.name)} · Web Transition Index</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="page">
    <header class="hero">
      <div>
        <div class="kicker">Web Transition Run</div>
        <h1>{esc(run_root.name)}</h1>
        <p>{esc("같은 입력에 대한 step-by-step 결과를 task별로 모아둔 인덱스입니다.")}</p>
        <div class="metric-row">
          <div class="metric"><div class="value">{total}</div><div class="label">tasks</div></div>
          <div class="metric"><div class="value">{selected}</div><div class="label">selected outputs</div></div>
          <div class="metric"><div class="value">{candidate_total}</div><div class="label">candidate steps</div></div>
          <div class="metric"><div class="value">{len(baseline_names) or 1}</div><div class="label">baselines</div></div>
        </div>
      </div>
      <div style="min-width:280px;max-width:420px">
        <div class="metric-row" style="margin-top:0">
          <div class="metric" style="flex:1 1 100%">
            <div class="label">Baselines</div>
            <div class="small" style="color:#e2e8f0;line-height:1.7">{esc(", ".join(baseline_names) or "default")}</div>
          </div>
          <div class="metric" style="flex:1 1 100%">
            <div class="label">Root</div>
            <div class="small" style="color:#e2e8f0;line-height:1.7">{esc(str(run_root))}</div>
          </div>
        </div>
      </div>
    </header>

    <div class="index-grid">
      {''.join(cards)}
    </div>
  </div>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="eval_results")
    parser.add_argument("--open", action="store_true", help="Open the generated HTML in the system browser")
    args = parser.parse_args()

    path = Path(args.path)
    if (path / "result.json").exists():
        bundle = load_task_bundle(path)
        out = path / "viz_io.html"
        write_html(out, render_task_page(bundle))
        print(out)
        if args.open:
            subprocess.run(["open", str(out)], check=False)
        return

    task_dirs = discover_task_dirs(path)
    if not task_dirs:
        raise SystemExit(f"No task result folders found under {path}")

    bundles = [load_task_bundle(task_dir) for task_dir in task_dirs]
    for bundle in bundles:
        task_dir = Path(bundle["task_dir"])
        write_html(task_dir / "viz_io.html", render_task_page(bundle))

    out = path / "transition_viewer.html"
    write_html(out, render_run_index_page(path, bundles))
    print(out)
    if args.open:
        subprocess.run(["open", str(out)], check=False)


if __name__ == "__main__":
    main()
