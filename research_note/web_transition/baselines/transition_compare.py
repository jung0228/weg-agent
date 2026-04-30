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
import json
import os
import re
import subprocess
from collections import OrderedDict
from pathlib import Path
from typing import Any

from baseline_profiles import BASELINE_PROFILES
from transition_viewer import (
    CSS,
    chip,
    discover_task_dirs,
    esc,
    first_line,
    load_task_bundle,
)

FAMILY_LABELS = {
    "memory": "Memory",
    "world_model": "World model",
}

FAMILY_TONES = {
    "memory": "gray",
    "world_model": "indigo",
}

CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
STEP_DIR_RE = re.compile(r"^S(\d+)$")


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


def compact_source_label(bundle: dict[str, Any]) -> str:
    metadata = bundle.get("metadata", {})
    baseline = str(metadata.get("baseline") or "").strip()
    if baseline:
        return baseline
    model = str(metadata.get("model") or "").strip()
    if model:
        return model
    return source_label(bundle)


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


def slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    slug = re.sub(r"_+", "_", slug).strip("._-")
    return slug or "task"


def natural_sort_key(path: Path) -> tuple[Any, ...]:
    parts = re.split(r"(\d+)", path.name)
    key: list[Any] = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        elif part:
            key.append(part.lower())
    return tuple(key)


def discover_step_dirs(task_dir: Path) -> list[Path]:
    if not task_dir.exists():
        return []
    step_dirs = [path for path in task_dir.iterdir() if path.is_dir() and STEP_DIR_RE.fullmatch(path.name)]
    return sorted(
        step_dirs,
        key=lambda path: int(STEP_DIR_RE.fullmatch(path.name).group(1)),  # type: ignore[union-attr]
    )


def read_text_or_placeholder(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return f"[missing: {path.name}]"


def parse_json_text(text: str) -> Any:
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return parsed if isinstance(parsed, (dict, list)) else {}


def load_json_or_none(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def join_preview(items: list[str], limit: int = 3) -> str:
    cleaned = [item for item in (str(item).strip() for item in items) if item]
    if not cleaned:
        return "—"
    if len(cleaned) <= limit:
        return " · ".join(cleaned)
    return " · ".join(cleaned[:limit]) + f" · +{len(cleaned) - limit} more"


def render_raw_file_block(label: str, content: str) -> str:
    return f"""
      <div class="raw-file">
        <div class="raw-file-head">
          <span class="raw-file-name">{esc(label)}</span>
        </div>
        <pre>{esc(content or "—")}</pre>
      </div>
    """


def render_collapsible_raw_file_block(label: str, content: str, open_by_default: bool = False) -> str:
    preview = first_line(content, 140) or "—"
    open_attr = " open" if open_by_default else ""
    return f"""
      <details class="raw-file raw-file-collapsible"{open_attr}>
        <summary>
          <span class="raw-file-name">{esc(label)}</span>
          <span class="raw-file-preview">{esc(preview)}</span>
        </summary>
        <pre>{esc(content or "—")}</pre>
      </details>
    """


def render_baseline_output_strip(bundle: dict[str, Any]) -> str:
    task_dir = Path(bundle.get("task_dir", ""))
    result_json = read_text_or_placeholder(task_dir / "result.json")
    step1_json = read_text_or_placeholder(task_dir / "S1" / "llm_output.json")
    selected_action = str(bundle.get("result", {}).get("selected_action", "—"))
    selection_reason = str(bundle.get("result", {}).get("selection_reason", ""))
    return f"""
      <section class="raw-output-strip">
        <div class="section-label">Model raw output</div>
        <div class="raw-output-grid">
          <div class="raw-output-main">
            {render_raw_file_block("result.json", result_json)}
          </div>
          <div class="raw-output-side">
            {render_raw_file_block("S1/llm_output.json", step1_json)}
            <div class="raw-output-meta">
              <div class="raw-output-meta-row"><span>selected_action</span><b>{esc(selected_action)}</b></div>
              <div class="raw-output-meta-row"><span>selection_reason</span><div>{esc(selection_reason or "—")}</div></div>
            </div>
          </div>
        </div>
      </section>
    """


def find_task_images(task_dir: Path) -> list[Path]:
    patterns = ["screenshot*.png", "screenshot*.webp", "screenshot*.jpg", "step*.png", "*.png"]
    seen: list[Path] = []
    for pattern in patterns:
        for path in sorted(task_dir.glob(pattern), key=natural_sort_key):
            if path.name in {".DS_Store"}:
                continue
            if path not in seen:
                seen.append(path)
    return seen


def render_snapshot_document(bundle: dict[str, Any]) -> str:
    """Wrap the task preview in a standalone document so Chrome can rasterize it."""
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(bundle.get("task_name", "Task"))} · Snapshot</title>
  <style>{CSS}
{COMPARE_CSS}</style>
</head>
<body>
  <div class="page" style="padding:24px">
    {render_task_preview(bundle)}
  </div>
</body>
</html>
"""


def ensure_snapshot_asset(bundle: dict[str, Any], compare_root: Path) -> dict[str, str]:
    """Return a renderable asset for the task snapshot, generating one if needed."""
    task_dir = Path(bundle.get("task_dir", ""))
    existing = find_task_images(task_dir)
    if existing:
        try:
            return {"kind": "image", "src": os.path.relpath(existing[0], start=compare_root)}
        except ValueError:
            return {"kind": "image", "src": str(existing[0])}

    task_name = str(bundle.get("task_name", task_dir.name or "task"))
    source_label = str(bundle.get("source_label", "source"))
    asset_dir = compare_root / ".web_transition_assets" / slugify(task_name) / slugify(source_label)
    asset_dir.mkdir(parents=True, exist_ok=True)
    viz_io_path = task_dir / "viz_io.html"
    png_name = "raw_viz_io.png" if viz_io_path.exists() else "snapshot.png"
    png_path = asset_dir / png_name
    src_paths = [
        task_dir / "result.json",
        task_dir / "interact_messages.json",
        task_dir / "metadata.json",
        task_dir / "user_prompt.txt",
        task_dir / "system_prompt.txt",
        viz_io_path,
    ]
    source_mtime = max((p.stat().st_mtime for p in src_paths if p.exists()), default=0.0)

    if viz_io_path.exists():
        if (not png_path.exists()) or png_path.stat().st_mtime < source_mtime:
            try:
                subprocess.run(
                    [
                        CHROME_BIN,
                        "--headless",
                        "--disable-gpu",
                        "--hide-scrollbars",
                        "--window-size=1600,1200",
                        f"--screenshot={png_path}",
                        f"file://{viz_io_path.resolve()}",
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

        if png_path.exists():
            try:
                return {"kind": "image", "src": os.path.relpath(png_path, start=compare_root)}
            except ValueError:
                return {"kind": "image", "src": str(png_path)}

    html_path = asset_dir / "snapshot.html"
    html_path.write_text(render_snapshot_document(bundle), encoding="utf-8")
    if (not png_path.exists()) or png_path.stat().st_mtime < max(source_mtime, html_path.stat().st_mtime):
        try:
            subprocess.run(
                [
                    CHROME_BIN,
                    "--headless",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    "--window-size=1600,1200",
                    f"--screenshot={png_path}",
                    f"file://{html_path}",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            # Fall back to the raw HTML path if Chrome capture is unavailable.
            try:
                return {"kind": "html", "src": os.path.relpath(html_path, start=compare_root)}
            except ValueError:
                return {"kind": "html", "src": str(html_path)}

    try:
        return {"kind": "image", "src": os.path.relpath(png_path, start=compare_root)}
    except ValueError:
        return {"kind": "image", "src": str(png_path)}


def render_task_preview(bundle: dict[str, Any]) -> str:
    payload = bundle.get("payload", {})
    observation = payload.get("observation", {})
    if not isinstance(observation, dict):
        observation = {}
    visible_regions = observation.get("visible_regions", [])
    if not isinstance(visible_regions, list):
        visible_regions = []
    salient_elements = observation.get("salient_elements", [])
    if not isinstance(salient_elements, list):
        salient_elements = []
    candidate_actions = payload.get("candidate_actions", [])
    if not isinstance(candidate_actions, list):
        candidate_actions = []

    visible_pills = "".join(chip(region, "indigo") for region in visible_regions) or '<div class="small">-</div>'
    action_cards = []
    for action in candidate_actions:
        if not isinstance(action, dict):
            continue
        action_cards.append(
            f"""
            <div class="preview-action-pill">
              <b>{esc(action.get("id", ""))}</b>
              <span>{esc(action.get("surface", ""))}</span>
            </div>
            """
        )

    element_cards = []
    for index, element in enumerate(salient_elements, start=1):
        if not isinstance(element, dict):
            continue
        element_cards.append(
            f"""
            <div class="preview-element">
              <div class="preview-element-head">
                <span class="preview-element-id">{esc(element.get("id", f"e{index}"))}</span>
                <span class="preview-element-role">{esc(element.get("role", ""))}</span>
              </div>
              <div class="preview-element-text">{esc(element.get("text", ""))}</div>
              <div class="preview-element-meta">
                <span>{esc(element.get("region", ""))}</span>
                <span>{esc(element.get("context", ""))}</span>
              </div>
            </div>
            """
        )

    return f"""
      <section class="panel preview-panel">
        <div class="section-label">S1 State Image</div>
        <div class="preview-shell">
          <div class="preview-topbar">
            <div class="preview-dots"><span></span><span></span><span></span></div>
            <div class="preview-topbar-center">
              <span class="preview-step">S1</span>
              <span class="preview-address">{esc(observation.get("page_type", "page"))} · {esc(bundle.get("task_name", "Task"))}</span>
            </div>
          </div>
          <div class="preview-body">
            <aside class="preview-sidebar">
              <div class="preview-sidebar-title">Visible regions</div>
              <div class="chips preview-chips">{visible_pills}</div>
              <div class="preview-sidebar-title" style="margin-top:14px">Task</div>
              <div class="preview-task">{esc(payload.get("task", ""))}</div>
              <div class="preview-sidebar-title" style="margin-top:14px">Actions</div>
              <div class="preview-action-stack">
                {''.join(action_cards) or '<div class="small">No candidate actions.</div>'}
              </div>
            </aside>
            <main class="preview-main">
              <div class="preview-main-head">
                <div class="preview-main-kicker">Observation</div>
                <div class="preview-main-title">{esc(observation.get("page_type", "—"))}</div>
              </div>
              <div class="preview-element-grid">
                {''.join(element_cards) or '<div class="small">No salient elements.</div>'}
              </div>
            </main>
          </div>
        </div>
      </section>
    """


def render_task_snapshot_panel(bundle: dict[str, Any], compare_root: Path) -> str:
    asset = ensure_snapshot_asset(bundle, compare_root)
    src = asset.get("src", "")
    kind = asset.get("kind", "image")
    if kind == "html":
        media = f'<iframe class="snapshot-media snapshot-iframe" src="{esc(src)}" loading="lazy"></iframe>'
    else:
        media = f'<img class="snapshot-media snapshot-img" src="{esc(src)}" alt="S1 state snapshot" />'
    task_dir = Path(bundle.get("task_dir", ""))
    viz_io = task_dir / "viz_io.html"

    return f"""
      <section class="panel snapshot-panel raw-snapshot-panel">
        <div class="section-label">Raw task image</div>
        <div class="snapshot-stage">
          <div class="snapshot-frame">
            {media}
          </div>
          <div class="snapshot-caption">
            <span class="snapshot-step">S1</span>
            <span class="snapshot-title">visual snapshot</span>
            <span class="snapshot-subtitle">{esc(bundle.get("task_name", "Task"))}</span>
          </div>
          <div class="small" style="line-height:1.7">
            <b>Source:</b> {esc(str(viz_io)) if viz_io.exists() else "generated snapshot fallback"}
          </div>
        </div>
      </section>
    """


def render_raw_step_gallery(bundle: dict[str, Any], compare_root: Path) -> str:
    task_dir = Path(bundle.get("task_dir", ""))
    step_dirs = discover_step_dirs(task_dir)
    if not step_dirs:
        return '<div class="small">No raw step directories found.</div>'

    cards = []
    for step_dir in step_dirs:
        system_prompt = read_text_or_placeholder(step_dir / "system_prompt.txt")
        user_prompt = read_text_or_placeholder(step_dir / "user_prompt.txt")
        metadata = read_text_or_placeholder(step_dir / "metadata.json")
        llm_output = read_text_or_placeholder(step_dir / "llm_output.json")
        acc_tree = read_text_or_placeholder(step_dir / "acc_tree.txt")
        cards.append(
            f"""
            <article class="raw-step-card">
              <div class="raw-step-head">
                <div>
                  <div class="raw-step-step">{esc(step_dir.name)}</div>
                  <div class="raw-step-title">Raw input / output</div>
                </div>
                <div class="meta">no parsing</div>
              </div>
              <div class="raw-step-grid">
                <div class="raw-step-column">
                  <div class="raw-section-label">Input</div>
                  {render_raw_file_block("system_prompt.txt", system_prompt)}
                  {render_raw_file_block("user_prompt.txt", user_prompt)}
                  {render_raw_file_block("metadata.json", metadata)}
                </div>
                <div class="raw-step-column">
                  <div class="raw-section-label">Output</div>
                  {render_raw_file_block("llm_output.json", llm_output)}
                  {render_raw_file_block("acc_tree.txt", acc_tree)}
                </div>
              </div>
            </article>
            """
        )

    return f"""
      <section class="raw-step-gallery">
        <div class="section-label">Raw step IO</div>
        <div class="stack-inner">
          {''.join(cards)}
        </div>
      </section>
    """


def ensure_reasoningbank_step_asset(
    bundle: dict[str, Any],
    compare_root: Path,
    step_dir: Path,
) -> dict[str, str]:
    task_dir = Path(bundle.get("task_dir", ""))
    task_name = str(bundle.get("task_name", task_dir.name or "task"))
    source_label = str(bundle.get("source_label", "source"))
    asset_dir = compare_root / ".web_transition_assets" / slugify(task_name) / slugify(source_label) / "reasoningbank"
    asset_dir.mkdir(parents=True, exist_ok=True)

    snapshot_asset = ensure_snapshot_asset(bundle, compare_root)
    snapshot_src = snapshot_asset.get("src", "")
    snapshot_ref = Path(snapshot_src).name if snapshot_src else ""
    metadata_text = read_text_or_placeholder(step_dir / "metadata.json")
    metadata = {}
    try:
        metadata = json.loads(metadata_text)
    except Exception:
        metadata = {}
    step_label = step_dir.name
    candidate_id = str(metadata.get("candidate_id", "")).strip() or "?"

    html_path = asset_dir / f"{step_label}.html"
    png_path = asset_dir / f"{step_label}.png"
    html_path.write_text(
        f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(task_name)} · {esc(step_label)}</title>
  <style>
    body {{
      margin: 0;
      background: #f8fafc;
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #0f172a;
      padding: 18px;
    }}
    .frame {{
      border: 1px solid rgba(15,23,42,.12);
      border-radius: 20px;
      background: white;
      box-shadow: 0 18px 40px rgba(15,23,42,.08);
      overflow: hidden;
    }}
    .head {{
      display:flex;
      justify-content:space-between;
      gap:12px;
      align-items:center;
      padding:14px 16px;
      border-bottom:1px solid rgba(15,23,42,.08);
      background: linear-gradient(180deg,#fff 0%,#f8fafc 100%);
    }}
    .badge {{
      display:inline-flex;
      align-items:center;
      gap:8px;
      padding:4px 10px;
      border-radius:999px;
      background:#e0e7ff;
      color:#3730a3;
      font-size:11px;
      font-weight:900;
      letter-spacing:.08em;
      text-transform:uppercase;
    }}
    .subtitle {{
      font-size:12px;
      color:#64748b;
      line-height:1.5;
      max-width:42ch;
      text-align:right;
    }}
    img {{
      display:block;
      width:100%;
      height:auto;
    }}
    .caption {{
      display:flex;
      gap:10px;
      align-items:center;
      flex-wrap:wrap;
      padding:12px 16px;
      border-top:1px solid rgba(15,23,42,.08);
    }}
    .step {{
      display:inline-flex;
      align-items:center;
      padding:4px 10px;
      border-radius:999px;
      background:#0f172a;
      color:#fff;
      font-size:11px;
      font-weight:900;
      letter-spacing:.08em;
    }}
    .step-title {{
      font-size:15px;
      font-weight:900;
    }}
    .muted {{
      font-size:12px;
      color:#64748b;
    }}
  </style>
</head>
<body>
  <div class="frame">
    <div class="head">
      <div>
        <div class="badge">ReasoningBank capture</div>
        <div style="margin-top:8px;font-size:20px;font-weight:900;letter-spacing:-.02em">{esc(task_name)}</div>
      </div>
      <div class="subtitle">
        Same observed page state, but the raw prompt/output differs by step.
        <br />Candidate: {esc(candidate_id)}
      </div>
    </div>
    <img src="{esc(snapshot_ref)}" alt="{esc(step_label)}" />
    <div class="caption">
      <span class="step">{esc(step_label)}</span>
      <span class="step-title">ReasoningBank raw capture</span>
      <span class="muted">candidate {esc(candidate_id)}</span>
    </div>
  </div>
</body>
</html>
""",
        encoding="utf-8",
    )

    snapshot_path = Path(snapshot_src)
    if snapshot_src and not snapshot_path.is_absolute():
        snapshot_path = Path(compare_root) / snapshot_path
    if (not png_path.exists()) or png_path.stat().st_mtime < max(
        (step_dir / "metadata.json").stat().st_mtime if (step_dir / "metadata.json").exists() else 0,
        (step_dir / "llm_output.json").stat().st_mtime if (step_dir / "llm_output.json").exists() else 0,
        (step_dir / "system_prompt.txt").stat().st_mtime if (step_dir / "system_prompt.txt").exists() else 0,
        (step_dir / "user_prompt.txt").stat().st_mtime if (step_dir / "user_prompt.txt").exists() else 0,
        snapshot_path.stat().st_mtime if snapshot_src and snapshot_path.exists() else 0,
        html_path.stat().st_mtime,
    ):
        try:
            subprocess.run(
                [
                    CHROME_BIN,
                    "--headless",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    "--window-size=1600,1200",
                    f"--screenshot={png_path}",
                    f"file://{html_path.resolve()}",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    try:
        return {"kind": "image", "src": os.path.relpath(png_path, start=compare_root)}
    except ValueError:
        return {"kind": "image", "src": str(png_path)}


def render_reasoningbank_focus(bundle: dict[str, Any], compare_root: Path) -> str:
    task_dir = Path(bundle.get("task_dir", ""))
    step_dirs = discover_step_dirs(task_dir)
    if not step_dirs:
        return '<div class="small">No reasoningbank step directories found.</div>'

    step_assets = [ensure_reasoningbank_step_asset(bundle, compare_root, step_dir) for step_dir in step_dirs]
    step_meta = []
    for step_dir in step_dirs:
        metadata_text = read_text_or_placeholder(step_dir / "metadata.json")
        try:
            step_meta.append(json.loads(metadata_text))
        except Exception:
            step_meta.append({})
    memory_items = reasoningbank_memory_items(bundle)
    memory_markdown = render_reasoningbank_memory_markdown(memory_items)

    slide_buttons = "".join(
        f'<button class="slide-btn{" active" if idx == 0 else ""}" onclick="showReasoningbankStep({idx})">{esc(step_dir.name)}</button>'
        for idx, step_dir in enumerate(step_dirs)
    )
    slides = []
    for idx, (asset, meta, step_dir) in enumerate(zip(step_assets, step_meta, step_dirs)):
        caption = f"{step_dir.name} · {meta.get('candidate_id', '')}"
        slides.append(
            f"""
            <div class="slide {'active' if idx == 0 else ''}" id="rb-slide-{idx}">
              <img class="rb-slide-img" src="{esc(asset.get('src', ''))}" alt="{esc(caption)}" />
              <div class="step-label">{esc(caption)}</div>
            </div>
            """
        )

    raw_blocks = []
    for step_dir, meta, memory_item in zip(step_dirs, step_meta, memory_items):
        memory_markdown = render_reasoningbank_memory_markdown([memory_item])
        raw_blocks.append(
            f"""
            <article class="raw-step-card">
              <div class="raw-step-head">
                <div>
                  <div class="raw-step-step">{esc(step_dir.name)}</div>
                  <div class="raw-step-title">ReasoningBank memory item</div>
                </div>
                <div class="meta">paper format</div>
              </div>
              <div class="raw-step-grid">
                <div class="raw-step-column">
                  <div class="raw-section-label">Input</div>
                  {render_raw_file_block("system_prompt.txt", read_text_or_placeholder(step_dir / "system_prompt.txt"))}
                  {render_raw_file_block("user_prompt.txt", read_text_or_placeholder(step_dir / "user_prompt.txt"))}
                  {render_raw_file_block("metadata.json", read_text_or_placeholder(step_dir / "metadata.json"))}
                </div>
                <div class="raw-step-column">
                  <div class="raw-section-label">Output</div>
                  {render_raw_file_block("memory_item.md", memory_markdown)}
                  {render_collapsible_raw_file_block("llm_output.json", read_text_or_placeholder(step_dir / "llm_output.json"))}
                  {render_raw_file_block("acc_tree.txt", read_text_or_placeholder(step_dir / "acc_tree.txt"))}
                </div>
              </div>
            </article>
            """
        )

    result_json = read_text_or_placeholder(task_dir / "result.json")
    interact_messages = read_text_or_placeholder(task_dir / "interact_messages.json")
    return f"""
      <section class="reasoningbank-focus">
        <div class="section-label">ReasoningBank memory extraction</div>
        <div class="raw-output-grid" style="grid-template-columns:minmax(420px,0.9fr) minmax(520px,1.1fr)">
          <div class="raw-output-side">
            <div class="slider-wrap reasoningbank-slider">
              <div class="slides">
                {''.join(slides)}
              </div>
              <div class="thumbs" style="margin-top:10px">{slide_buttons}</div>
            </div>
            <div class="raw-output-meta">
              <div class="raw-output-meta-row">
                <span>memory_items.md</span>
                <div>{esc(first_line(memory_markdown, 240))}</div>
              </div>
              <div class="raw-output-meta-row">
                <span>result.json</span>
                <div>{esc(first_line(result_json, 240))}</div>
              </div>
              <div class="raw-output-meta-row">
                <span>interact_messages.json</span>
                <div>{esc(first_line(interact_messages, 240))}</div>
              </div>
            </div>
            <details class="raw-file raw-file-collapsible" open>
              <summary>
                <span class="raw-file-name">memory_items.md</span>
                <span class="raw-file-preview">ReasoningBank prompt format: Title / Description / Content</span>
              </summary>
              <pre>{esc(memory_markdown)}</pre>
            </details>
          </div>
          <div class="raw-output-main">
            <div class="stack-inner">
              <div class="card mini">
                <div class="card-title">
                  <h3>Episode-level extraction</h3>
                  <span class="meta">paper aligned</span>
                </div>
                <div class="small" style="color:var(--muted);line-height:1.7">
                  The raw trajectory is distilled into up to three reusable memory items, each written as Title / Description / Content and appended to the bank.
                </div>
                <div class="raw-preview">
                  {''.join(render_reasoningbank_memory_item_cards(memory_items))}
                </div>
              </div>
              {''.join(raw_blocks)}
            </div>
          </div>
        </div>
        <script>
        function showReasoningbankStep(index) {{
          const slides = document.querySelectorAll('.reasoningbank-slider .slide');
          const buttons = document.querySelectorAll('.slide-btn');
          slides.forEach((slide, i) => slide.classList.toggle('active', i === index));
          buttons.forEach((btn, i) => btn.classList.toggle('active', i === index));
        }}
        </script>
      </section>
    """


def render_reasoningbank_step_row(
    bundle: dict[str, Any],
    compare_root: Path,
    step_dir: Path,
    step_label: str,
) -> str:
    metadata_text = read_text_or_placeholder(step_dir / "metadata.json")
    llm_output = read_text_or_placeholder(step_dir / "llm_output.json")
    system_prompt = read_text_or_placeholder(step_dir / "system_prompt.txt")
    user_prompt = read_text_or_placeholder(step_dir / "user_prompt.txt")
    acc_tree = read_text_or_placeholder(step_dir / "acc_tree.txt")
    metadata = parse_json_text(metadata_text)
    user_payload = parse_json_text(user_prompt)
    llm_payload = parse_json_text(llm_output)
    candidate_id = str(metadata.get("candidate_id") or "—")
    task_text = str(user_payload.get("task") or "—")
    obs = user_payload.get("observation") if isinstance(user_payload.get("observation"), dict) else {}
    visible_regions = obs.get("visible_regions", []) if isinstance(obs.get("visible_regions", []), list) else []
    salient_elements = obs.get("salient_elements", []) if isinstance(obs.get("salient_elements", []), list) else []
    candidate_actions = user_payload.get("candidate_actions", []) if isinstance(user_payload.get("candidate_actions", []), list) else []
    retrieved_memory = user_payload.get("retrieved_transition_memory", []) if isinstance(user_payload.get("retrieved_transition_memory", []), list) else []

    salient_preview = []
    for element in salient_elements[:3]:
        if not isinstance(element, dict):
            continue
        salient_preview.append(
            f"{element.get('id', 'element')}: {element.get('text', '')} [{element.get('region', '')}]"
        )

    candidate_preview = []
    for action in candidate_actions[:4]:
        if not isinstance(action, dict):
            continue
        candidate_preview.append(
            f"{action.get('id', 'candidate')} {action.get('surface', '')} → {action.get('target', '')}"
        )

    memory_preview = []
    for memory in retrieved_memory[:3]:
        if not isinstance(memory, dict):
            continue
        memory_preview.append(
            f"{memory.get('action_affordance', 'memory')}: {memory.get('expected_transition', '')}"
        )

    candidate_evals = llm_payload.get("candidate_evaluations", []) if isinstance(llm_payload.get("candidate_evaluations", []), list) else []
    eval_preview = []
    for entry in candidate_evals[:4]:
        if not isinstance(entry, dict):
            continue
        eval_preview.append(
            f"{entry.get('id', 'candidate')}: {entry.get('memory_view', '')}"
        )

    return f"""
      <article class="rb-step-row">
        <div class="rb-step-topline">
          <div>
            <div class="raw-step-step">{esc(step_label)} · {esc(step_dir.name)}</div>
            <div class="raw-step-title">Action turn</div>
          </div>
          <div class="meta">what the policy LLM reads and emits</div>
        </div>
        <div class="rb-step-body">
          <div class="rb-step-note">This is the action-selection turn. Retrieved memory is part of the input, and the bank is only updated later after the episode finishes.</div>
          <div class="rb-step-io-grid">
            <section class="rb-step-panel">
              <div class="rb-step-panel-head">
                <span class="rb-phase-kicker">Input</span>
                <span class="meta">what goes into the LLM</span>
              </div>
              <div class="rb-step-panel-title">{esc(task_text)}</div>
              <div class="rb-step-panel-grid">
                <div class="rb-step-field">
                  <span>Observation</span>
                  <div>page_type: {esc(str(obs.get("page_type") or "—"))}</div>
                  <div>visible_regions: {esc(join_preview([str(x) for x in visible_regions]))}</div>
                  <div>salient: {esc(join_preview(salient_preview, limit=3))}</div>
                </div>
                <div class="rb-step-field">
                  <span>Candidate actions</span>
                  <div>{esc(join_preview(candidate_preview, limit=4))}</div>
                </div>
                <div class="rb-step-field">
                  <span>Retrieved memory</span>
                  <div>{esc(join_preview(memory_preview, limit=3))}</div>
                </div>
                <div class="rb-step-field full">
                  <span>Prompt packet</span>
                  <div>system_prompt.txt + user_prompt.txt + metadata.json</div>
                </div>
              </div>
            </section>
            <div class="rb-step-arrow" aria-hidden="true">→</div>
            <section class="rb-step-panel">
              <div class="rb-step-panel-head">
                <span class="rb-phase-kicker">Output</span>
                <span class="meta">what comes out</span>
              </div>
              <div class="rb-step-panel-title">{esc(str(llm_payload.get("selected_action") or metadata.get("selected_action") or "—"))}</div>
              <div class="rb-step-panel-grid">
                <div class="rb-step-field">
                  <span>Selected action</span>
                  <div>{esc(str(llm_payload.get("selected_action") or metadata.get("selected_action") or "—"))}</div>
                </div>
                <div class="rb-step-field">
                  <span>Selection reason</span>
                  <div>{esc(str(llm_payload.get("selection_reason") or "—"))}</div>
                </div>
                <div class="rb-step-field">
                  <span>Candidate evaluations</span>
                  <div>{esc(join_preview(eval_preview, limit=3))}</div>
                </div>
                <div class="rb-step-field full">
                  <span>Raw model output</span>
                  <div>{esc(first_line(llm_output, 220))}</div>
                </div>
              </div>
            </section>
          </div>
          <details style="margin-top:12px">
            <summary>Raw files</summary>
            <div class="raw-step-grid" style="margin-top:12px">
              <div class="raw-step-column">
                <div class="raw-section-label">Input</div>
                {render_collapsible_raw_file_block("system_prompt.txt", system_prompt)}
                {render_collapsible_raw_file_block("user_prompt.txt", user_prompt)}
                {render_raw_file_block("metadata.json", metadata_text)}
              </div>
              <div class="raw-step-column">
                <div class="raw-section-label">Output</div>
                {render_collapsible_raw_file_block("llm_output.json", llm_output)}
                <details class="raw-file raw-file-collapsible" open>
                  <summary>
                    <span class="raw-file-name">acc_tree.txt</span>
                    <span class="raw-file-preview">{esc(first_line(acc_tree, 140))}</span>
                  </summary>
                  <pre>{esc(acc_tree)}</pre>
                </details>
              </div>
            </div>
          </details>
        </div>
      </article>
    """


def render_reasoningbank_memory_checkpoint(
    step_label: str,
    memory_item: dict[str, str],
    bank_before_count: int,
    cumulative_items: list[dict[str, str]],
) -> str:
    bank_after_count = len(cumulative_items)
    bank_entries = []
    for idx, item in enumerate(cumulative_items, start=1):
        bank_entries.append(
            f"""
            <li{' class="is-new"' if idx == bank_after_count else ''}>
              <b>{esc(item["title"])}</b>
              <span>{esc(item["description"])}</span>
            </li>
            """
        )

    return f"""
      <article class="rb-memory-checkpoint">
        <div class="rb-memory-checkpoint-head">
          <div>
            <div class="snapshot-step">Memory bank growth · {esc(step_label)}</div>
            <div class="rb-memory-checkpoint-title">What gets appended after this trace</div>
          </div>
          <div class="meta">{bank_before_count} → {bank_after_count} items</div>
        </div>
        <div class="rb-memory-checkpoint-grid">
          <div class="rb-memory-checkpoint-box">
            <span>New memory item</span>
            <strong>{esc(memory_item["title"])}</strong>
            <p>{esc(memory_item["description"])}</p>
            <p class="rb-memory-checkpoint-content">{esc(memory_item["content"])}</p>
          </div>
          <div class="rb-memory-checkpoint-box">
            <span>Bank after this step</span>
            <ol class="rb-memory-checkpoint-list">
              {''.join(bank_entries)}
            </ol>
          </div>
        </div>
      </article>
    """


def reasoningbank_memory_items(bundle: dict[str, Any]) -> list[dict[str, str]]:
    task_dir = Path(bundle.get("task_dir", ""))
    result_json = read_text_or_placeholder(task_dir / "result.json")
    try:
        result = json.loads(result_json)
    except Exception:
        result = {}

    candidate_evaluations = result.get("candidate_evaluations") or []
    titles_by_id = {
        "a1": {
            "title": "Follow the organic result path",
            "description": "Use when the page mixes primary results with sponsored detours and the task needs the main flow to advance.",
            "content": (
                "Select the genuine result card to enter the primary workflow. "
                "Treat a detail panel or modal as progress even if the URL does not change, "
                "and avoid sponsored tiles unless the instruction explicitly asks for them."
            ),
        },
        "a2": {
            "title": "Treat sponsored panels as workflow detours",
            "description": "Use when banners or deal links may branch away from the main task.",
            "content": (
                "Sponsored items usually route to unrelated promotional flows. "
                "Prefer them only when the instruction explicitly calls for a deal path; "
                "otherwise stay on the main result list and verify the next page remains in the intended workflow."
            ),
        },
        "a4": {
            "title": "Use sorting controls only for exploration",
            "description": "Use when a page offers sorting or filter menus but the goal is to move the workflow forward.",
            "content": (
                "Sorting can help compare options, but it rarely advances the task state. "
                "Open it only if ordering is needed, and treat it as progress only when it exposes an actionable list or refreshed result set."
            ),
        },
    }

    items: list[dict[str, str]] = []
    for idx, entry in enumerate(candidate_evaluations, start=1):
        cid = str(entry.get("id") or f"item-{idx}")
        spec = titles_by_id.get(cid)
        memory_view = str(entry.get("memory_view") or "").strip()
        if spec is None:
            lowered = memory_view.lower()
            if "sponsor" in lowered or "promo" in lowered:
                spec = titles_by_id["a2"]
            elif "sort" in lowered:
                spec = titles_by_id["a4"]
            else:
                spec = titles_by_id["a1"]
        items.append(
            {
                "id": cid,
                "title": spec["title"],
                "description": spec["description"],
                "content": spec["content"],
                "source_signal": memory_view or str(entry.get("selection_reason") or "—"),
                "source_transition": str(entry.get("expected_transition") or "—"),
                "source_failure": str(entry.get("failure_signal") or "—"),
                "source_verification": str(entry.get("verification_rule") or "—"),
            }
        )
    return items


def render_reasoningbank_memory_markdown(items: list[dict[str, str]]) -> str:
    blocks = []
    for idx, item in enumerate(items, start=1):
        blocks.append(
            "\n".join(
                [
                    f"# Memory Item {idx}",
                    f"## Title {item['title']}",
                    f"## Description {item['description']}",
                    f"## Content {item['content']}",
                ]
            )
        )
    return "\n\n".join(blocks)


def render_reasoningbank_memory_item_cards(items: list[dict[str, str]]) -> str:
    cards = []
    for idx, item in enumerate(items, start=1):
        cards.append(
            f"""
            <div class="rb-phase-card">
              <div class="rb-phase-top">
                <span class="snapshot-step">Memory Item {idx}</span>
                <span class="rb-phase-kicker">{esc(item["id"])}</span>
              </div>
              <div class="rb-phase-title">{esc(item["title"])}</div>
              <div class="rb-phase-io">
                <div>
                  <span>Description</span>
                  <p>{esc(item["description"])}</p>
                </div>
                <div>
                  <span>Content</span>
                  <p>{esc(item["content"])}</p>
                </div>
              </div>
              <div class="rb-phase-note">{esc(item["source_signal"])}</div>
            </div>
            """
        )
    return "".join(cards)


def render_reasoningbank_method_map(bundle: dict[str, Any], compare_root: Path) -> str:
    task_dir = Path(bundle.get("task_dir", ""))
    memory_items = reasoningbank_memory_items(bundle)
    phase_cards = []
    phase_definitions = [
        (
            "Retrieval",
            "search relevant memory items",
            "current task + observation + memory bank",
            "retrieved lessons injected into the prompt",
            "The repo retrieves the most relevant reasoning lessons from the bank and concatenates them into the agent prompt.",
        ),
        (
            "Extraction",
            "distill a reusable lesson from the episode",
            "trajectory + reward signal + autoeval thoughts",
            "Markdown memory item with Title / Description / Content",
            "This is where a successful or failed trajectory is turned into a reusable lesson.",
        ),
        (
            "Consolidation",
            "append the lesson to the bank",
            "structured memory item (Title / Description / Content)",
            "JSONL bank entry plus embedding cache update",
            "The bank is append-only, so future tasks can retrieve the lesson again.",
        ),
    ]
    for idx, (phase, headline, input_text, output_text, note) in enumerate(phase_definitions):
        step_note = memory_items[idx]["title"] if idx < len(memory_items) else phase
        phase_cards.append(
            f"""
            <div class="rb-phase-card">
              <div class="rb-phase-top">
                <span class="snapshot-step">{esc(step_note)}</span>
                <span class="rb-phase-kicker">{esc(phase)}</span>
              </div>
              <div class="rb-phase-title">{esc(headline)}</div>
              <div class="rb-phase-io">
                <div>
                  <span>Input</span>
                  <p>{esc(input_text)}</p>
                </div>
                <div>
                  <span>Output</span>
                  <p>{esc(output_text)}</p>
                </div>
              </div>
              <div class="rb-phase-note">{esc(note)}</div>
            </div>
            """
        )

    schema_block = f"""
      <div class="rb-schema-card">
        <div class="rb-schema-head">
          <span class="rb-phase-kicker">Memory item schema</span>
          <span class="meta">paper-aligned</span>
        </div>
        <div class="rb-schema-grid">
          <div><span>Title</span><p>교훈을 압축한 짧은 이름</p></div>
          <div><span>Description</span><p>언제 쓰고 언제 쓰지 말아야 하는지 설명하는 한 문장</p></div>
          <div><span>Content</span><p>1-3문장으로 적은 reusable lesson / pitfall / strategy</p></div>
        </div>
      </div>
    """

    return f"""
      <section class="reasoningbank-method-map">
        <div class="section-label">Blog-aligned reasoning loop</div>
        <p class="baseline-intro">ReasoningBank는 raw trajectory를 그대로 저장하는 대신, 성공/실패에서 뽑은 lesson을 bank에 쌓고, retrieval 때는 그 lesson을 prompt에 넣어 행동을 고르는 closed loop다.</p>
        <div class="rb-phase-grid">
          {''.join(phase_cards)}
        </div>
        {schema_block}
        <div class="small" style="margin-top:12px; color:var(--muted); line-height:1.7">
          retrieval는 bank에서 관련 lesson을 읽고, extraction은 episode를 보고 새 lesson을 뽑고, consolidation은 그 lesson을 다음 task를 위한 bank item으로 추가한다.
        </div>
      </section>
    """


def load_reasoningbank_episode_trace(task_dir: Path) -> dict[str, Any] | None:
    parsed = load_json_or_none(task_dir / "reasoningbank_episode_trace.json")
    return parsed if isinstance(parsed, dict) else None


def render_episode_memory_cards(
    items: list[dict[str, Any]],
    highlight_ids: set[str] | None = None,
    *,
    compact: bool = False,
) -> str:
    highlight_ids = highlight_ids or set()
    cards = []
    for item in items:
        item_id = str(item.get("id") or "memory")
        class_names = ["rb-episode-memory-card"]
        if item_id in highlight_ids:
            class_names.append("is-highlighted")
        if compact:
            class_names.append("is-compact")
        body = (
            f"<p>{esc(str(item.get('description') or '—'))}</p>"
            if compact
            else f"""
              <p>{esc(str(item.get("description") or "—"))}</p>
              <div>{esc(str(item.get("content") or "—"))}</div>
            """
        )
        cards.append(
            f"""
            <div class="{' '.join(class_names)}">
              <div class="rb-memory-card-top">
                <span class="snapshot-step">{esc(item_id)}</span>
                {chip("retrieved", "teal") if item_id in highlight_ids else ""}
              </div>
              <strong>{esc(str(item.get("title") or "Memory item"))}</strong>
              {body}
            </div>
            """
        )
    return "".join(cards) if cards else '<div class="rb-empty-state">No memory items yet.</div>'


def episode_action_chain(episode: dict[str, Any]) -> list[dict[str, str]]:
    steps = episode.get("steps", [])
    if not isinstance(steps, list):
        return []
    chain = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        observation = step.get("observation", {})
        observation = observation if isinstance(observation, dict) else {}
        llm_output = step.get("llm_output", {})
        llm_output = llm_output if isinstance(llm_output, dict) else {}
        env_result = step.get("environment_result", {})
        env_result = env_result if isinstance(env_result, dict) else {}
        chain.append(
            {
                "label": str(step.get("label") or f"Step {step.get('step', '')}"),
                "state": str(observation.get("state_id") or "state"),
                "action": str(llm_output.get("action") or llm_output.get("selected_action") or "—"),
                "next_state": str(env_result.get("next_state_id") or "—"),
            }
        )
    return chain


def render_action_chain(chain: list[dict[str, str]]) -> str:
    if not chain:
        return ""
    items = []
    for entry in chain:
        items.append(
            f"""
            <div class="rb-chain-item">
              <span>{esc(entry["label"])}</span>
              <b>{esc(entry["state"])}</b>
              <code>{esc(entry["action"])}</code>
              <em>→ {esc(entry["next_state"])}</em>
            </div>
            """
        )
    return f'<div class="rb-chain">{"".join(items)}</div>'


def render_previous_trajectory(previous_steps: list[dict[str, Any]]) -> str:
    if not previous_steps:
        return '<div class="rb-trajectory-empty">none yet. This is the first action turn.</div>'
    entries = []
    for prev in previous_steps:
        if not isinstance(prev, dict):
            continue
        llm_output = prev.get("llm_output", {})
        llm_output = llm_output if isinstance(llm_output, dict) else {}
        env_result = prev.get("environment_result", {})
        env_result = env_result if isinstance(env_result, dict) else {}
        entries.append(
            f"""
            <li>
              <b>{esc(str(prev.get("label") or f"Step {prev.get('step', '')}"))}</b>
              <span>{esc(str(llm_output.get("action") or "—"))}</span>
              <em>→ {esc(str(env_result.get("next_state_id") or "—"))}</em>
            </li>
            """
        )
    return f'<ol class="rb-trajectory-list">{"".join(entries)}</ol>'


def render_retrieval_scores(scores: list[Any]) -> str:
    rows = []
    for score in scores:
        if not isinstance(score, dict):
            continue
        rows.append(
            f"""
            <li>
              <b>{esc(str(score.get("id") or "memory"))}</b>
              <span>{esc(str(score.get("score") or "—"))}</span>
              <em>{esc(str(score.get("reason") or "—"))}</em>
            </li>
            """
        )
    return f'<ol class="rb-score-list">{"".join(rows)}</ol>' if rows else ""


def render_pre_policy_modules(step: dict[str, Any]) -> str:
    action_module = step.get("action_space_builder", {})
    action_module = action_module if isinstance(action_module, dict) else {}
    memory_module = step.get("memory_retriever", {})
    memory_module = memory_module if isinstance(memory_module, dict) else {}
    scores = memory_module.get("scores", [])
    scores = scores if isinstance(scores, list) else []

    return f"""
      <div class="rb-prepolicy-grid">
        <section class="rb-prepolicy-card">
          <div class="rb-prepolicy-head">
            <span class="rb-phase-kicker">GitHub component 1</span>
            <strong>Action-space prompt</strong>
          </div>
          <p class="rb-prepolicy-note">{esc(str(action_module.get("ownership") or "environment / browser wrapper"))}</p>
          <div class="rb-module-io">
            <div><span>Input</span><p>{esc(str(action_module.get("input") or "current browser observation / accessibility tree"))}</p></div>
            <div><span>How</span><p>{esc(str(action_module.get("method") or "enumerate visible interactive elements and convert them to legal actions"))}</p></div>
            <div><span>Output</span><p>{esc(str(action_module.get("output") or "candidate_actions"))}</p></div>
          </div>
        </section>
        <section class="rb-prepolicy-card">
          <div class="rb-prepolicy-head">
            <span class="rb-phase-kicker">GitHub component 2</span>
            <strong>Memory selector / prompt injection</strong>
          </div>
          <p class="rb-prepolicy-note">{esc(str(memory_module.get("ownership") or "ReasoningBank retrieval module"))}</p>
          <div class="rb-module-io">
            <div><span>Input</span><p>{esc(str(memory_module.get("input") or "task + observation + trajectory + memory bank"))}</p></div>
            <div><span>Query / ranking</span><p>{esc(str(memory_module.get("query") or memory_module.get("method") or "semantic similarity over memory items"))}</p></div>
            <div><span>Output</span><p>{esc(str(memory_module.get("output") or "retrieved_memory"))}</p></div>
          </div>
          {render_retrieval_scores(scores)}
        </section>
      </div>
      <div class="rb-module-flow-note">GitHub 기준으로는 <b>candidate_actions JSON</b>이 따로 저장되는 것이 아니라 action-space description과 AXTree가 prompt에 들어간다. 아래 candidate list는 발표용으로 AXTree/action space에서 사람이 읽기 쉽게 재구성한 것이다.</div>
    """


def render_reasoningbank_executive_summary(episode: dict[str, Any]) -> str:
    initial_bank = episode.get("initial_bank", [])
    initial_items = [item for item in initial_bank if isinstance(item, dict)] if isinstance(initial_bank, list) else []
    steps = episode.get("steps", [])
    step_count = len(steps) if isinstance(steps, list) else 0
    extraction = episode.get("extraction", {})
    extraction = extraction if isinstance(extraction, dict) else {}
    extracted_items = extraction.get("items", [])
    extracted_count = len(extracted_items) if isinstance(extracted_items, list) else 0
    consolidation = episode.get("consolidation", {})
    consolidation = consolidation if isinstance(consolidation, dict) else {}
    before_count = consolidation.get("bank_before_count", len(initial_items))
    after_count = consolidation.get("bank_after_count", len(initial_items) + extracted_count)
    judge = episode.get("judge", {})
    judge = judge if isinstance(judge, dict) else {}

    summary_cards = [
        (
            "Before LLM",
            "Action-space prompt",
            "AXTree/HTML observation과 BrowserGym HighLevelActionSet 설명을 prompt에 넣는다.",
            "GitHub에는 candidate_actions JSON 모듈이 없다.",
        ),
        (
            "Before episode",
            "Memory selector",
            "task intent로 reasoning_bank JSONL을 검색해 memory_path를 만들고, 이 text를 매 step system prompt에 붙인다.",
            "GitHub WebArena path는 step마다 재검색하지 않는다.",
        ),
        (
            "During action",
            "Policy LLM",
            "AXTree/HTML observation + action-space prompt + selected memory_path text + history를 보고 action string을 생성한다.",
            "이때 memory bank는 업데이트되지 않고 읽히기만 한다.",
        ),
        (
            "After episode",
            "Memory write",
            f"전체 trajectory + judge={judge.get('output', '—')}를 보고 {extracted_count}개 lesson을 추출한다.",
            f"seeded prior bank: {before_count} → after episode: {after_count}",
        ),
    ]
    cards = []
    for phase, title, main, note in summary_cards:
        cards.append(
            f"""
            <div class="rb-exec-card">
              <span>{esc(phase)}</span>
              <strong>{esc(title)}</strong>
              <p>{esc(main)}</p>
              <em>{esc(note)}</em>
            </div>
            """
        )

    return f"""
      <section class="reasoningbank-exec">
        <div class="section-label">Executive summary</div>
        <div class="rb-exec-head">
          <div>
            <h2>ReasoningBank는 action 중에는 memory를 읽고, episode 후에만 memory를 쓴다.</h2>
            <p>
              이 페이지는 flight task 하나를 실제 episode처럼 펼쳐서, LLM에 무엇이 들어가고 무엇이 나오는지, 그리고 어떤 lesson이 최종 bank에 저장되는지 보여준다.
            </p>
          </div>
          <div class="rb-exec-metrics">
            <div><b>{step_count}</b><span>action turns</span></div>
            <div><b>{before_count} → {after_count}</b><span>seeded prior → final bank</span></div>
            <div><b>{esc(str(judge.get("output") or "—"))}</b><span>judge result</span></div>
          </div>
        </div>
        <div class="rb-exec-grid">
          {''.join(cards)}
        </div>
        {render_action_chain(episode_action_chain(episode))}
      </section>
    """


def render_episode_initial_bank(episode: dict[str, Any]) -> str:
    initial_bank = episode.get("initial_bank", [])
    items = initial_bank if isinstance(initial_bank, list) else []
    initial_bank_note = str(
        episode.get("initial_bank_note")
        or "These are seeded prior-memory examples for the demo, not a claim that a cold-start ReasoningBank run always begins with two items."
    )
    return f"""
      <article class="rb-episode-card">
        <div class="rb-step-topline">
          <div>
            <div class="raw-step-step">Initial value · seeded prior memory</div>
            <div class="raw-step-title">Memory bank available before this task</div>
          </div>
          <div class="meta">{len(items)} seeded items</div>
        </div>
        <div class="rb-step-note">
          {esc(initial_bank_note)} action LLM은 매 스텝에서 여기서 관련 item을 retrieval해서 prompt input으로 받는다.
        </div>
        <div class="rb-episode-memory-grid">
          {render_episode_memory_cards([item for item in items if isinstance(item, dict)])}
        </div>
      </article>
    """


def render_episode_step(
    step: dict[str, Any],
    bank_by_id: dict[str, dict[str, Any]],
    previous_steps: list[dict[str, Any]],
) -> str:
    observation = step.get("observation", {})
    observation = observation if isinstance(observation, dict) else {}
    visible_elements = observation.get("visible_elements", [])
    visible_elements = visible_elements if isinstance(visible_elements, list) else []
    candidate_actions = step.get("candidate_actions", [])
    candidate_actions = candidate_actions if isinstance(candidate_actions, list) else []
    retrieved_ids = [str(item) for item in step.get("retrieved_memory_ids", []) if str(item)]
    retrieved_items = [bank_by_id[item_id] for item_id in retrieved_ids if item_id in bank_by_id]
    llm_output = step.get("llm_output", {})
    llm_output = llm_output if isinstance(llm_output, dict) else {}
    env_result = step.get("environment_result", {})
    env_result = env_result if isinstance(env_result, dict) else {}
    bank_delta = step.get("bank_delta", {})
    bank_delta = bank_delta if isinstance(bank_delta, dict) else {}

    candidate_rows = []
    for action in candidate_actions:
        if not isinstance(action, dict):
            continue
        selected = str(action.get("id") or "") == str(llm_output.get("selected_action") or "")
        candidate_rows.append(
            f"""
            <li{' class="is-selected"' if selected else ''}>
              <b>{esc(str(action.get("id") or "candidate"))}</b>
              <span>{esc(str(action.get("action") or "—"))}</span>
              <em>{esc(str(action.get("surface") or ""))}</em>
            </li>
            """
        )

    raw_input = {
        "pre_policy_modules": {
            "action_space_builder": step.get("action_space_builder", {}),
            "memory_retriever": step.get("memory_retriever", {}),
        },
        "task": step.get("task"),
        "observation": observation,
        "selected_memory_from_memory_path": retrieved_items,
        "visualization_candidate_actions_not_repo_json": candidate_actions,
        "trajectory_so_far": [
            {
                "step": prev.get("step"),
                "action": (prev.get("llm_output", {}) if isinstance(prev.get("llm_output", {}), dict) else {}).get("action"),
                "next_state": (prev.get("environment_result", {}) if isinstance(prev.get("environment_result", {}), dict) else {}).get("next_state_id"),
            }
            for prev in previous_steps
            if isinstance(prev, dict)
        ],
    }
    raw_output = {
        "llm_output": llm_output,
        "environment_result": env_result,
        "bank_delta": bank_delta,
    }

    return f"""
      <article class="rb-episode-card">
        <div class="rb-step-topline">
          <div>
            <div class="raw-step-step">{esc(str(step.get("label") or f"Step {step.get('step', '')}"))} · action selection</div>
            <div class="raw-step-title">{esc(str(observation.get("state_id") or "state"))}</div>
          </div>
          <div class="meta">policy LLM turn</div>
        </div>
        <div class="rb-step-note">
          GitHub 구현 기준으로는 LLM 앞에 AXTree/HTML observation, action-space description, history, 그리고 episode 시작 전에 선택된 memory_path text가 들어간다. 아래 candidate list는 repo artifact가 아니라 이해를 위한 재구성이다.
        </div>
        {render_pre_policy_modules(step)}
        <div class="rb-step-io-grid">
          <section class="rb-step-panel">
            <div class="rb-step-panel-head">
              <span class="rb-phase-kicker">Input to LLM</span>
              <span class="meta">GitHub-style prompt packet</span>
            </div>
            <div class="rb-step-panel-title">{esc(str(step.get("llm_input_summary") or "task + observation + memory + candidates"))}</div>
            <div class="rb-step-panel-grid">
              <div class="rb-step-field full">
                <span>Task</span>
                <div>{esc(str(step.get("task") or "—"))}</div>
              </div>
              <div class="rb-step-field">
                <span>Observation</span>
                <div>{esc(str(observation.get("summary") or "—"))}</div>
              </div>
              <div class="rb-step-field">
                <span>Visible elements</span>
                <div>{esc(join_preview([str(item) for item in visible_elements], limit=5))}</div>
              </div>
              <div class="rb-step-field full">
                <span>Trajectory so far</span>
                {render_previous_trajectory(previous_steps)}
              </div>
              <div class="rb-step-field full">
                <span>Selected memory injected from memory_path</span>
                <div class="rb-inline-memory-list">
                  {render_episode_memory_cards(retrieved_items, set(retrieved_ids), compact=True)}
                </div>
              </div>
              <div class="rb-step-field full">
                <span>Visualization-only candidate actions</span>
                <ol class="rb-candidate-list">{''.join(candidate_rows)}</ol>
              </div>
            </div>
          </section>
          <div class="rb-step-arrow" aria-hidden="true">→</div>
          <section class="rb-step-panel">
            <div class="rb-step-panel-head">
              <span class="rb-phase-kicker">Output from LLM / env</span>
              <span class="meta">action + transition</span>
            </div>
            <div class="rb-step-panel-title">{esc(str(llm_output.get("action") or llm_output.get("selected_action") or "—"))}</div>
            <div class="rb-step-panel-grid">
              <div class="rb-step-field">
                <span>Thought</span>
                <div>{esc(str(llm_output.get("thought") or "—"))}</div>
              </div>
              <div class="rb-step-field">
                <span>Selected action</span>
                <div>{esc(str(llm_output.get("selected_action") or "—"))}</div>
              </div>
              <div class="rb-step-field">
                <span>Environment transition</span>
                <div>{esc(str(env_result.get("transition") or "—"))}</div>
              </div>
              <div class="rb-step-field">
                <span>Verification</span>
                <div>{esc(str(env_result.get("verification") or "—"))}</div>
              </div>
              <div class="rb-step-field full rb-bank-readonly">
                <span>Memory bank status</span>
                <div>{esc(str(bank_delta.get("before") or "0"))} → {esc(str(bank_delta.get("after") or "0"))} items. {esc(str(bank_delta.get("note") or "Read-only during the episode."))}</div>
              </div>
            </div>
          </section>
        </div>
        <details class="raw-file raw-file-collapsible">
          <summary>
            <span class="raw-file-name">raw input/output packet</span>
            <span class="raw-file-preview">exact JSON shown without extra parsing</span>
          </summary>
          <div class="raw-step-grid" style="margin-top:12px">
            <div class="raw-step-column">
              <div class="raw-section-label">Input</div>
              {render_raw_file_block("policy_input.json", json.dumps(raw_input, ensure_ascii=False, indent=2))}
            </div>
            <div class="raw-step-column">
              <div class="raw-section-label">Output</div>
              {render_raw_file_block("policy_output_and_env.json", json.dumps(raw_output, ensure_ascii=False, indent=2))}
            </div>
          </div>
        </details>
      </article>
    """


def render_episode_post_episode(episode: dict[str, Any]) -> str:
    extraction = episode.get("extraction", {})
    extraction = extraction if isinstance(extraction, dict) else {}
    consolidation = episode.get("consolidation", {})
    consolidation = consolidation if isinstance(consolidation, dict) else {}
    judge = episode.get("judge", {})
    judge = judge if isinstance(judge, dict) else {}
    extracted_items = extraction.get("items", [])
    extracted_items = extracted_items if isinstance(extracted_items, list) else []
    final_bank = episode.get("final_bank", [])
    final_bank = final_bank if isinstance(final_bank, list) else []

    before_count = int(consolidation.get("bank_before_count") or 0)
    append_cards = []
    running_count = before_count
    for item in extracted_items:
        if not isinstance(item, dict):
            continue
        running_count += 1
        source_steps = item.get("source_steps", [])
        source_steps = source_steps if isinstance(source_steps, list) else []
        append_cards.append(
            f"""
            <div class="rb-append-card">
              <div class="rb-memory-card-top">
                <span class="snapshot-step">append {esc(str(item.get("id") or ""))}</span>
                <span class="meta">{running_count - 1} → {running_count} items</span>
              </div>
              <strong>{esc(str(item.get("title") or "Memory item"))}</strong>
              <p>{esc(str(item.get("description") or "—"))}</p>
              <div>{esc(str(item.get("content") or "—"))}</div>
              <small>source: {esc(join_preview([str(step) for step in source_steps], limit=4))}</small>
            </div>
            """
        )

    raw_extraction = {
        "input": extraction.get("input"),
        "trajectory": episode_action_chain(episode),
        "judge": judge,
        "output_format": extraction.get("output_format"),
        "items": extracted_items,
    }

    return f"""
      <article class="rb-episode-card rb-post-episode-card">
        <div class="rb-step-topline">
          <div>
            <div class="raw-step-step">After episode · memory write</div>
            <div class="raw-step-title">Judge → extract lessons → append to bank</div>
          </div>
          <div class="meta">{esc(str(consolidation.get("bank_before_count") or 0))} → {esc(str(consolidation.get("bank_after_count") or len(final_bank)))} items</div>
        </div>
        <div class="rb-step-note">
          여기서부터 bank가 실제로 변한다. 위 3개 action turn 전체를 하나의 trajectory로 보고, 성공/실패 signal을 붙여 reusable lesson을 뽑은 뒤 다음 task에서 retrieval될 수 있도록 bank에 추가한다.
        </div>
        <div class="rb-post-grid">
          <section class="rb-step-panel">
            <div class="rb-step-panel-head">
              <span class="rb-phase-kicker">LLM-as-a-Judge</span>
              <span class="meta">episode signal</span>
            </div>
            <div class="rb-step-panel-title">{esc(str(judge.get("output") or "—"))}</div>
            <div class="rb-step-panel-grid">
              <div class="rb-step-field">
                <span>Input</span>
                <div>{esc(str(judge.get("input") or "—"))}</div>
              </div>
              <div class="rb-step-field">
                <span>Reason</span>
                <div>{esc(str(judge.get("reason") or "—"))}</div>
              </div>
            </div>
          </section>
          <section class="rb-step-panel">
            <div class="rb-step-panel-head">
              <span class="rb-phase-kicker">Memory extraction</span>
              <span class="meta">trajectory → lesson</span>
            </div>
            <div class="rb-step-panel-title">{esc(str(extraction.get("output_format") or "Title / Description / Content"))}</div>
            <div class="rb-step-panel-grid">
              <div class="rb-step-field">
                <span>Input</span>
                <div>{esc(str(extraction.get("input") or "—"))}</div>
              </div>
              <div class="rb-step-field">
                <span>Trajectory summary</span>
                {render_action_chain(episode_action_chain(episode))}
              </div>
              <div class="rb-step-field full">
                <span>Output</span>
                <div>{len(extracted_items)} reusable memory item(s) in Title / Description / Content format</div>
              </div>
            </div>
          </section>
        </div>
        <div class="rb-consolidation-block">
          <div class="rb-memory-card-top">
            <span class="rb-phase-kicker">Consolidation</span>
            <span class="meta">append-only bank update</span>
          </div>
          <div class="rb-append-grid">
            {''.join(append_cards)}
          </div>
        </div>
        <div class="rb-consolidation-block">
          <div class="rb-memory-card-top">
            <span class="rb-phase-kicker">Final memory bank for next task</span>
            <span class="meta">{len(final_bank)} items</span>
          </div>
          <div class="rb-episode-memory-grid">
            {render_episode_memory_cards([item for item in final_bank if isinstance(item, dict)], {str(item.get("id")) for item in extracted_items if isinstance(item, dict)})}
          </div>
        </div>
        <details class="raw-file raw-file-collapsible">
          <summary>
            <span class="raw-file-name">extraction_and_consolidation.json</span>
            <span class="raw-file-preview">post-episode memory write packet</span>
          </summary>
          {render_raw_file_block("memory_extraction.json", json.dumps(raw_extraction, ensure_ascii=False, indent=2))}
        </details>
      </article>
    """


def render_reasoningbank_episode_flow(episode: dict[str, Any]) -> str:
    initial_bank = episode.get("initial_bank", [])
    initial_items = [item for item in initial_bank if isinstance(item, dict)] if isinstance(initial_bank, list) else []
    bank_by_id = {str(item.get("id")): item for item in initial_items}
    steps = episode.get("steps", [])
    step_cards: list[str] = []
    previous_steps: list[dict[str, Any]] = []
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_cards.append(render_episode_step(step, bank_by_id, previous_steps))
            previous_steps.append(step)

    return f"""
      <section class="reasoningbank-step-list">
        <div class="section-label">Actual episode I/O</div>
        <p class="baseline-intro">
          GitHub 구현에 맞춰 보면, 각 action turn은 AXTree/HTML observation + action-space prompt + selected memory text를 받아 action string을 생성한다. 명시적인 candidate_actions JSON은 없으므로 아래 후보 목록은 발표용 재구성이다.
        </p>
        <div class="stack rb-episode-stack">
          {render_episode_initial_bank(episode)}
          {''.join(step_cards)}
          {render_episode_post_episode(episode)}
        </div>
      </section>
    """


def render_reasoningbank_memory_growth(bundle: dict[str, Any], compare_root: Path) -> str:
    task_dir = Path(bundle.get("task_dir", ""))
    step_dirs = discover_step_dirs(task_dir)
    if not step_dirs:
        return ""

    memory_items = reasoningbank_memory_items(bundle)
    cumulative_items: list[dict[str, str]] = []
    ribbon_items: list[str] = []
    cards: list[str] = []
    for idx, step_dir in enumerate(step_dirs, start=1):
        item = memory_items[idx - 1] if idx - 1 < len(memory_items) else {
            "id": f"item-{idx}",
            "title": f"Memory Item {idx}",
            "description": "ReasoningBank lesson",
            "content": "Generated memory item.",
            "source_signal": "—",
        }
        bank_before_count = len(cumulative_items)
        cumulative_items.append(item)
        bank_after_count = len(cumulative_items)
        ribbon_items.append(
            f"""
            <div class="rb-bank-ribbon-item">
              <div class="rb-bank-ribbon-step">Memory Item {idx}</div>
              <div class="rb-bank-ribbon-title">{esc(item["title"])}</div>
              <div class="rb-bank-ribbon-copy">{esc(item["description"])}</div>
              <div class="rb-bank-ribbon-count">{bank_before_count} → {bank_after_count} items</div>
            </div>
            """
        )

        bank_items = []
        for existing in cumulative_items:
            is_new = existing["id"] == item["id"]
            bank_items.append(
                f"""
                <li{ ' class="is-new"' if is_new else '' }>
                  <b>{esc(existing["title"])}</b>
                  <span>{esc(existing["description"])}</span>
                </li>
                """
            )

        cards.append(
            f"""
            <article class="rb-bank-card">
              <div class="rb-bank-head">
                <div>
                  <div class="rb-bank-step">Memory Item {idx}</div>
                  <div class="rb-bank-title">{esc(item["title"])}</div>
                </div>
                {chip("append", "teal")}
              </div>
              <div class="rb-bank-added">
                <div class="rb-bank-added-label">New memory item</div>
                <div class="rb-bank-added-value">{esc(item["description"])}</div>
              </div>
              <div class="rb-bank-delta">
                <div>
                  <span>Bank before</span>
                  <b>{bank_before_count} items</b>
                </div>
                <div>
                  <span>Bank after</span>
                  <b>{bank_after_count} items</b>
                </div>
                <div>
                  <span>Change</span>
                  <b>+1 appended</b>
                </div>
              </div>
              <div class="rb-bank-grid">
                <div>
                  <span>Description</span>
                  <p>{esc(item["description"])}</p>
                </div>
                <div>
                  <span>Content</span>
                  <p>{esc(item["content"])}</p>
                </div>
                <div>
                  <span>Source cue</span>
                  <p>{esc(item.get("source_signal", "—"))}</p>
                </div>
              </div>
              <div class="rb-bank-after">
                <div class="rb-bank-after-label">Bank after item {idx} · {bank_after_count} item(s)</div>
                <ol class="rb-bank-list">
                  {''.join(bank_items)}
                </ol>
              </div>
            </article>
            """
        )

    latest = cumulative_items[-1]
    summary = f"""
      <div class="rb-bank-summary">
        <div class="rb-bank-summary-item">
          <span>bank size</span>
          <b>{len(cumulative_items)} items</b>
        </div>
        <div class="rb-bank-summary-item">
          <span>latest item</span>
          <b>{esc(latest["title"])}</b>
        </div>
        <div class="rb-bank-summary-item">
          <span>latest description</span>
          <b>{esc(latest["description"])}</b>
        </div>
      </div>
      <div class="rb-bank-ribbon">
        {''.join(ribbon_items)}
      </div>
    """
    memory_markdown = render_reasoningbank_memory_markdown(cumulative_items)

    return f"""
      <section class="reasoningbank-memory-growth">
        <div class="section-label">Memory bank growth</div>
        <p class="baseline-intro">ReasoningBank는 episode에서 성공/실패의 교훈을 추출한 뒤 bank에 append한다. 아래는 이 task에서 뽑아낸 memory item을 paper format으로 다시 정리한 것이다.</p>
        {summary}
        <details class="raw-file raw-file-collapsible" open style="margin-bottom:14px">
          <summary>
            <span class="raw-file-name">memory_items.md</span>
            <span class="raw-file-preview">{esc(first_line(memory_markdown, 140))}</span>
          </summary>
          <pre>{esc(memory_markdown)}</pre>
        </details>
        <div class="stack">
          {''.join(cards)}
        </div>
      </section>
    """


def render_reasoningbank_page(bundle: dict[str, Any], compare_root: Path) -> str:
    task_dir = Path(bundle.get("task_dir", ""))
    step_dirs = discover_step_dirs(task_dir)
    if not step_dirs:
        return render_compare_page(compare_root, group_bundles([task_dir]))

    step_labels = [f"Step {idx}" for idx in range(1, len(step_dirs) + 1)]
    episode_trace = load_reasoningbank_episode_trace(task_dir)
    method_map = (
        render_reasoningbank_executive_summary(episode_trace)
        if episode_trace is not None
        else render_reasoningbank_method_map(bundle, compare_root)
    )
    task_snapshot = render_task_snapshot_panel(bundle, compare_root)
    memory_items = reasoningbank_memory_items(bundle)
    result_json = read_text_or_placeholder(task_dir / "result.json")
    interact_messages = read_text_or_placeholder(task_dir / "interact_messages.json")
    step_blocks = []
    cumulative_items: list[dict[str, str]] = []
    for idx, (step_dir, step_label) in enumerate(zip(step_dirs, step_labels)):
        step_blocks.append(render_reasoningbank_step_row(bundle, compare_root, step_dir, step_label))
        if idx < len(memory_items):
            cumulative_items.append(memory_items[idx])
            step_blocks.append(
                render_reasoningbank_memory_checkpoint(
                    step_label=step_label,
                    memory_item=memory_items[idx],
                    bank_before_count=len(cumulative_items) - 1,
                    cumulative_items=cumulative_items,
                )
            )
    step_rows = "".join(step_blocks)
    if episode_trace is not None:
        step_section = render_reasoningbank_episode_flow(episode_trace)
    else:
        step_section = f"""
    <section class="reasoningbank-step-list">
      <div class="section-label">Step-by-step captures</div>
      <p class="baseline-intro">각 스텝은 action turn의 input/output을 보여준다. action step에서는 memory를 읽기만 하고, episode가 끝난 뒤 extraction/consolidation 단계에서 bank가 업데이트된다.</p>
      <div class="stack">
        {step_rows}
      </div>
    </section>
        """
    task_name = bundle.get("task_name", "Task")
    display_task_name = "Flight booking task" if str(task_name).lower() == "flight" else str(task_name)
    task_text = str((episode_trace or {}).get("task") or bundle.get("payload", {}).get("task") or task_name)
    source_label_text = compact_source_label(bundle)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(display_task_name)} · ReasoningBank</title>
  <style>{CSS}
{COMPARE_CSS}</style>
</head>
<body>
  <div class="page reasoningbank-page">
    <header class="hero">
      <div>
        <div class="kicker">ReasoningBank focus</div>
        <h1>{esc(display_task_name)}</h1>
        <p>{esc(task_text)} · action-time retrieval, post-episode memory update</p>
        <div class="metric-row">
          <div class="metric"><div class="value">{len(step_dirs)}</div><div class="label">steps</div></div>
          <div class="metric"><div class="value">{esc(source_label_text)}</div><div class="label">source</div></div>
        </div>
      </div>
      <div style="min-width:280px;max-width:460px">
        <div class="metric-row" style="margin-top:0">
          <div class="metric" style="flex:1 1 100%">
            <div class="label">핵심</div>
            <div class="small" style="color:#e2e8f0;line-height:1.7">
              action 중에는 memory를 읽어서 action을 고르고, episode가 끝난 뒤에만 lesson을 추출해 bank에 쓴다.
            </div>
          </div>
          <div class="metric" style="flex:1 1 100%">
            <div class="label">읽는 순서</div>
            <div class="small" style="color:#e2e8f0;line-height:1.7">Executive summary → Actual episode I/O → Appendix raw files</div>
          </div>
        </div>
      </div>
    </header>

    {method_map}

    {step_section}

    <details class="rb-appendix">
      <summary>Appendix: exact stored files</summary>
      <div class="task-section reasoningbank-single reasoningbank-summary-stack" style="margin-top:12px">
        <div class="task-head">
          <div>
            <div class="section-label">Task snapshot</div>
            <h2>{esc(display_task_name)}</h2>
            <div class="small">{esc(task_text)}</div>
          </div>
          <div class="chips">
            {chip("ReasoningBank", "gray")}
            {chip("raw prompts", "indigo")}
          </div>
        </div>
        {task_snapshot}
        <div class="model-card reasoningbank-summary-card">
          <div class="card-title">
            <h3>Bundle raw files</h3>
            <span class="meta">task-level</span>
          </div>
          <div class="stack-inner">
            {render_collapsible_raw_file_block("result.json", result_json)}
            {render_collapsible_raw_file_block("interact_messages.json", interact_messages)}
          </div>
        </div>
      </div>
    </details>
  </div>
</body>
</html>
"""


def render_baseline_shelf() -> str:
    family_order = ["memory", "world_model"]
    family_sections = []
    for family in family_order:
        items = [
            (name, profile)
            for name, profile in BASELINE_PROFILES.items()
            if profile.get("family") == family
        ]
        if not items:
            continue

        cards = []
        for name, profile in items:
            tone = FAMILY_TONES.get(family, "gray")
            pipeline_items = profile.get("pipeline", []) or []
            pipeline_cards = []
            for step_index, step in enumerate(pipeline_items, start=1):
                pipeline_cards.append(
                    f"""
                    <div class="pipeline-step">
                      <div class="pipeline-step-head">
                        <span class="pipeline-index">Stage {step_index}</span>
                        <span class="pipeline-name">{esc(step.get("name", ""))}</span>
                      </div>
                      <div class="pipeline-io">
                        <div><span>Input</span><p>{esc(step.get("input", ""))}</p></div>
                        <div><span>Output</span><p>{esc(step.get("output", ""))}</p></div>
                      </div>
                    </div>
                    """
                )
            cards.append(
                f"""
                <article class="baseline-card">
                  <div class="baseline-card-top">
                    <div>
                      <div class="baseline-name">{esc(profile.get("display_name", name))}</div>
                      <div class="baseline-key">{esc(name)}</div>
                    </div>
                    {chip(FAMILY_LABELS.get(family, family), tone)}
                  </div>
                  <div class="baseline-row">
                    <span>Stored unit</span>
                    <b>{esc(profile.get("stored_unit", ""))}</b>
                  </div>
                  <div class="baseline-note">{esc(profile.get("memory_view_instruction", ""))}</div>
                  <div class="baseline-post">{esc(profile.get("post_update", ""))}</div>
                  <div class="pipeline-block">
                    <div class="pipeline-label">Intermediate IO</div>
                    <div class="pipeline-stack">
                      {''.join(pipeline_cards)}
                    </div>
                  </div>
                </article>
                """
            )

        family_sections.append(
            f"""
            <section class="family-block">
              <div class="family-head">
                <h3>{esc(FAMILY_LABELS.get(family, family))}</h3>
                <span class="meta">{len(items)} baselines</span>
              </div>
              <div class="baseline-grid">
                {''.join(cards)}
              </div>
            </section>
            """
        )

    return f"""
      <section class="baseline-shelf">
        <div class="section-label">Baseline Shelf</div>
        <p class="baseline-intro">Memory / world-model baselines를 한 화면에서 같이 본다. 아직 결과가 없어도 baseline 정의는 항상 보인다.</p>
        <div class="stack">
          {''.join(family_sections)}
        </div>
      </section>
    """


def render_model_card(bundle: dict[str, Any], compare_root: Path) -> str:
    metadata = bundle.get("metadata", {})
    result = bundle.get("result", {})
    task_dir = Path(bundle.get("task_dir", ""))
    baseline_name = str(metadata.get("baseline") or "").strip() or compact_source_label(bundle)
    profile = BASELINE_PROFILES.get(baseline_name, {})
    selected_action = result.get("selected_action", "—")
    task_name = bundle.get("task_name", "Task")
    try:
        rel_html = os.path.relpath(task_dir / "viz_io.html", start=compare_root)
        rel_result = os.path.relpath(task_dir / "result.json", start=compare_root)
    except ValueError:
        rel_html = str(task_dir / "viz_io.html")
        rel_result = str(task_dir / "result.json")

    output_strip = render_baseline_output_strip(bundle)
    result_json = read_text_or_placeholder(task_dir / "result.json")
    metadata_json = read_text_or_placeholder(task_dir / "metadata.json")
    interact_messages = read_text_or_placeholder(task_dir / "interact_messages.json")
    assistant_output = read_text_or_placeholder(task_dir / "assistant_output.txt")

    if baseline_name == "reasoningbank":
        detail_body = render_reasoningbank_focus(bundle, compare_root)
    else:
        detail_body = render_raw_step_gallery(bundle, compare_root)

    return f"""
      <article class="model-card">
        <div class="card-title">
          <h3>{esc(baseline_name)}</h3>
          <span class="meta">{esc(selected_action)}</span>
        </div>
        <div class="chips" style="margin-bottom:10px">
          {chip(profile.get("family", "") or "baseline", "teal")}
          {chip(task_name, "gray")}
        </div>
        {output_strip}
        {detail_body}
        <details style="margin-top:12px">
          <summary>Bundle raw files</summary>
          <div class="stack-inner" style="margin-top:10px">
            {render_raw_file_block("result.json", result_json)}
            {render_raw_file_block("metadata.json", metadata_json)}
            {render_raw_file_block("interact_messages.json", interact_messages)}
            {render_raw_file_block("assistant_output.txt", assistant_output)}
          </div>
        </details>
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
    input_panel = render_task_snapshot_panel(shared_bundle, compare_root)
    model_cards = "".join(render_model_card(bundle, compare_root) for bundle in bundles)
    source_labels = sorted({compact_source_label(bundle) for bundle in bundles if compact_source_label(bundle)})
    explanation = "왼쪽은 raw task image이고, 오른쪽은 각 baseline의 step 폴더 안 원본 파일(system/user prompt, llm_output, acc_tree, metadata)을 그대로 보여준다."
    return f"""
      <section class="task-section">
        <div class="task-head">
          <div>
            <div class="section-label">Task</div>
            <h2>{esc(group.get("task_name", "Task"))}</h2>
            <div class="small">{esc(shared_bundle.get("payload", {}).get("task", ""))}</div>
            <div class="small task-explainer" style="margin-top:8px; color: var(--muted); line-height:1.65">{esc(explanation)}</div>
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
            compact_source_label(bundle)
            for group in groups
            for bundle in group.get("bundles", [])
            if compact_source_label(bundle)
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

    {render_baseline_shelf()}
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

.baseline-shelf {
  margin-top: 18px;
  background: rgba(255, 255, 255, 0.70);
  border: 1px solid var(--line);
  border-radius: 28px;
  padding: 18px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(12px);
}

.baseline-intro {
  margin: 0 0 14px;
  color: var(--muted);
  line-height: 1.6;
}

.family-block + .family-block {
  margin-top: 16px;
}

.family-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  margin-bottom: 12px;
}

.family-head h3 {
  margin: 0;
  font-size: 16px;
  letter-spacing: -0.02em;
}

.baseline-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 12px;
}

.baseline-card {
  border: 1px solid var(--line);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.92);
  padding: 14px;
}

.baseline-card-top {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: flex-start;
  margin-bottom: 10px;
}

.baseline-name {
  font-weight: 900;
  font-size: 16px;
  line-height: 1.1;
}

.baseline-key {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--muted);
  margin-top: 4px;
}

.baseline-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: baseline;
  font-size: 12px;
  margin: 8px 0;
  color: #334155;
}

.baseline-row span {
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.11em;
  font-size: 11px;
}

.baseline-note {
  font-size: 13px;
  line-height: 1.55;
  color: #1e293b;
  min-height: 3.1em;
}

.baseline-post {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed rgba(15, 23, 42, 0.12);
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

.pipeline-block {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(15, 23, 42, 0.08);
}

.pipeline-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 10px;
}

.pipeline-stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.pipeline-step {
  border: 1px solid var(--line);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.82);
  padding: 12px;
}

.pipeline-step-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  margin-bottom: 8px;
}

.pipeline-index {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--muted);
  font-weight: 800;
}

.pipeline-name {
  font-weight: 900;
  font-size: 14px;
  color: #0f172a;
}

.pipeline-io {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.pipeline-io span {
  display: inline-block;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 4px;
}

.pipeline-io p {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: #1e293b;
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
  grid-template-columns: minmax(420px, 0.90fr) minmax(760px, 1.82fr);
  gap: 16px;
  margin-top: 16px;
  align-items: start;
}

.preview-panel {
  align-self: start;
}

.preview-shell {
  overflow: hidden;
  border-radius: 24px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.75);
}

.preview-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  background: #0f172a;
  color: #cbd5e1;
}

.preview-topbar-center {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  min-width: 0;
}

.preview-step {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  background: #2563eb;
  color: white;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
}

.preview-dots {
  display: flex;
  gap: 6px;
}

.preview-dots span {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  display: inline-block;
  background: #475569;
}

.preview-dots span:first-child { background: #ef4444; }
.preview-dots span:nth-child(2) { background: #f59e0b; }
.preview-dots span:nth-child(3) { background: #22c55e; }

.preview-address {
  text-align: right;
  font-size: 11px;
  color: #93c5fd;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-body {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 0;
  min-height: 530px;
}

.preview-sidebar {
  padding: 14px;
  background: #e2e8f0;
  border-right: 1px solid rgba(15, 23, 42, 0.10);
}

.preview-sidebar-title {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 900;
  color: #64748b;
  margin-bottom: 8px;
}

.preview-chips {
  margin-bottom: 0;
}

.preview-task {
  font-size: 13px;
  line-height: 1.65;
  color: #1e293b;
}

.preview-action-stack {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.preview-action-pill {
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 14px;
  padding: 10px 12px;
}

.preview-action-pill b {
  display: block;
  font-size: 13px;
  color: #0f172a;
  margin-bottom: 2px;
}

.preview-action-pill span {
  display: block;
  font-size: 11px;
  color: #64748b;
}

.preview-main {
  padding: 16px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}

.preview-main-head {
  margin-bottom: 12px;
}

.preview-main-kicker {
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-size: 10px;
  font-weight: 900;
  color: var(--muted);
}

.preview-main-title {
  margin-top: 4px;
  font-size: 17px;
  font-weight: 900;
  letter-spacing: -0.02em;
  color: #0f172a;
}

.preview-element-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}

.preview-element {
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.05);
  padding: 12px;
  min-height: 120px;
}

.preview-element-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.preview-element-id {
  font-weight: 900;
  color: #0f172a;
}

.preview-element-role {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.10em;
  font-weight: 800;
  color: #64748b;
}

.preview-element-text {
  font-size: 13px;
  line-height: 1.55;
  color: #0f172a;
}

.preview-element-meta {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: #64748b;
}

.raw-preview {
  margin-top: 10px;
}

.snapshot-panel {
  position: sticky;
  top: 16px;
  align-self: start;
}

.snapshot-stage {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.snapshot-frame {
  overflow: hidden;
  border-radius: 24px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #fff;
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
}

.snapshot-media {
  display: block;
  width: 100%;
  height: auto;
}

.snapshot-iframe {
  min-height: 900px;
  border: 0;
}

.snapshot-caption {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.snapshot-step {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  background: #0f172a;
  color: #fff;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
}

.snapshot-title {
  font-size: 15px;
  font-weight: 900;
  color: #0f172a;
}

.snapshot-subtitle {
  font-size: 12px;
  color: var(--muted);
}

.model-strip {
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow: visible;
}

.raw-snapshot-panel .small {
  color: var(--muted);
}

.raw-output-strip {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(15, 23, 42, 0.08);
}

.raw-output-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
  gap: 12px;
  align-items: start;
}

.raw-output-side {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.raw-output-meta {
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.88);
  padding: 12px;
}

.raw-output-meta-row + .raw-output-meta-row {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed rgba(15, 23, 42, 0.10);
}

.raw-output-meta-row span {
  display: block;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 4px;
}

.raw-output-meta-row b,
.raw-output-meta-row div {
  display: block;
  font-size: 12px;
  line-height: 1.55;
  color: #0f172a;
  word-break: break-word;
}

.slider-wrap {
  position: relative;
}

.slides {
  position: relative;
}

.slide {
  display: none;
}

.slide.active {
  display: block;
}

.rb-slide-img {
  width: 100%;
  display: block;
  border-radius: 16px;
  border: 1px solid rgba(15, 23, 42, 0.10);
  background: white;
}

.step-label {
  text-align: center;
  font-size: 12px;
  color: #64748b;
  margin-top: 8px;
}

.slide-btn {
  padding: 7px 14px;
  border-radius: 999px;
  border: 1px solid #cbd5e1;
  background: white;
  color: #0f172a;
  cursor: pointer;
  font-size: 12px;
  font-weight: 800;
}

.slide-btn.active {
  background: #0f172a;
  color: white;
  border-color: #0f172a;
}

.reasoningbank-slider .thumbs {
  gap: 8px;
}

.shared-input {
  align-self: start;
}

.model-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 100%;
  width: 100%;
}

.model-card .links {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.raw-step-gallery {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(15, 23, 42, 0.08);
}

.raw-step-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.raw-step-column {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.raw-step-card {
  margin: 0;
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.86);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
  padding: 14px;
}

.raw-step-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
  margin-bottom: 10px;
}

.raw-step-step {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--muted);
  font-weight: 800;
}

.raw-step-title {
  font-weight: 900;
  font-size: 14px;
  color: #0f172a;
  line-height: 1.4;
  margin-top: 4px;
}

.raw-section-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 8px;
}

.raw-file {
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.88);
  overflow: hidden;
}

.raw-file + .raw-file {
  margin-top: 10px;
}

.raw-file-head {
  padding: 10px 12px 0;
}

.raw-file-name {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  background: #e2e8f0;
  color: #0f172a;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.raw-file pre {
  margin: 0;
  padding: 10px 12px 12px;
  max-height: 280px;
  overflow: auto;
  background: transparent;
  border: 0;
}

.raw-file-collapsible {
  margin-top: 0;
  padding: 0;
}

.raw-file-collapsible summary {
  list-style: none;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  padding: 10px 12px;
}

.raw-file-collapsible summary::-webkit-details-marker {
  display: none;
}

.raw-file-preview {
  flex: 1;
  min-width: 0;
  text-align: right;
  font-size: 11px;
  line-height: 1.4;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reasoningbank-memory-growth {
  margin-top: 16px;
  background: rgba(255, 255, 255, 0.74);
  border: 1px solid var(--line);
  border-radius: 28px;
  padding: 18px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(12px);
}

.rb-bank-summary {
  display: grid;
  grid-template-columns: 1fr 1fr 1.6fr;
  gap: 10px;
  margin: 12px 0 16px;
}

.rb-bank-summary-item {
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.92);
  padding: 12px 14px;
}

.rb-bank-summary-item span {
  display: block;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 6px;
}

.rb-bank-summary-item b {
  display: block;
  font-size: 13px;
  line-height: 1.55;
  color: #0f172a;
  word-break: break-word;
}

.rb-bank-ribbon {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.rb-bank-ribbon-item {
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.98), rgba(255, 255, 255, 0.98));
  padding: 12px;
}

.rb-bank-ribbon-step {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 900;
  color: var(--muted);
}

.rb-bank-ribbon-title {
  margin-top: 4px;
  font-size: 13px;
  font-weight: 900;
  line-height: 1.4;
  color: #0f172a;
  word-break: break-word;
}

.rb-bank-ribbon-copy {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.55;
  color: #1e293b;
  word-break: break-word;
}

.rb-bank-ribbon-count {
  margin-top: 8px;
  font-size: 11px;
  font-weight: 800;
  color: #0f766e;
}

.rb-bank-card {
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.92);
  padding: 14px;
}

.rb-bank-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
}

.rb-bank-step {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 900;
  color: var(--muted);
}

.rb-bank-title {
  margin-top: 4px;
  font-size: 15px;
  line-height: 1.35;
  font-weight: 900;
  color: #0f172a;
  white-space: normal;
  overflow-wrap: anywhere;
}

.rb-bank-added {
  margin-top: 12px;
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 18px;
  background: #f8fafc;
  padding: 12px;
}

.rb-bank-added-label,
.rb-bank-after-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 6px;
}

.rb-bank-added-value {
  font-size: 13px;
  line-height: 1.6;
  color: #0f172a;
}

.rb-bank-delta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.rb-bank-delta > div {
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.92);
  padding: 10px 12px;
}

.rb-bank-delta span {
  display: block;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 4px;
}

.rb-bank-delta b {
  display: block;
  font-size: 12px;
  line-height: 1.55;
  color: #0f172a;
}

.rb-bank-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.rb-bank-grid > div {
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 16px;
  background: white;
  padding: 10px 12px;
}

.rb-bank-grid span {
  display: block;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 4px;
}

.rb-bank-grid p {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: #1e293b;
}

.rb-step-memory {
  margin-top: 12px;
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 18px;
  background: #f8fafc;
  padding: 12px;
}

.rb-step-memory-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.rb-step-memory-title {
  margin-top: 6px;
  font-size: 14px;
  line-height: 1.45;
  font-weight: 900;
  color: #0f172a;
}

.rb-step-memory-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.rb-step-memory-grid > div {
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 16px;
  background: white;
  padding: 10px 12px;
}

.rb-step-memory-grid span {
  display: block;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 4px;
}

.rb-step-memory-grid p {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: #1e293b;
}

.reasoningbank-explainer {
  margin-top: 18px;
}

.rb-explain-flow {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 28px minmax(0, 1fr) 28px minmax(0, 1fr);
  gap: 10px;
  align-items: stretch;
  margin-top: 14px;
}

.rb-explain-card {
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 20px;
  background: linear-gradient(180deg, rgba(255,255,255,0.99), rgba(248,250,252,0.94));
  padding: 14px;
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.04);
}

.rb-explain-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.rb-explain-head strong {
  font-size: 15px;
  line-height: 1.35;
  font-weight: 900;
  color: #0f172a;
}

.rb-explain-io {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
}

.rb-explain-io > div {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 16px;
  background: white;
  padding: 10px 12px;
}

.rb-explain-io span {
  display: block;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 4px;
}

.rb-explain-io p {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: #0f172a;
  overflow-wrap: anywhere;
}

.rb-explain-note {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--muted);
}

.rb-explain-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: 900;
  color: var(--muted);
  opacity: 0.75;
}

.rb-step-row {
  margin-top: 18px;
}

.rb-step-topline {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.rb-step-topline .raw-step-step {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  color: var(--muted);
  font-weight: 800;
}

.rb-step-topline .raw-step-title {
  margin-top: 4px;
  font-size: 17px;
  line-height: 1.35;
  font-weight: 900;
  color: #0f172a;
}

.rb-step-note {
  margin: 6px 0 12px;
  font-size: 13px;
  line-height: 1.65;
  color: var(--muted);
}

.rb-step-io-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 28px minmax(0, 1fr);
  gap: 12px;
  margin-top: 12px;
  align-items: start;
}

.rb-step-panel {
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(248,250,252,0.96));
  padding: 14px;
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.04);
}

.rb-step-panel-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.rb-step-panel-title {
  margin-top: 6px;
  font-size: 15px;
  line-height: 1.45;
  font-weight: 900;
  color: #0f172a;
  overflow-wrap: anywhere;
}

.rb-step-panel-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.rb-step-field {
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 16px;
  background: white;
  padding: 10px 12px;
}

.rb-step-field.full {
  grid-column: 1 / -1;
}

.rb-step-field span {
  display: block;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 4px;
}

.rb-step-field div,
.rb-step-field p {
  overflow-wrap: anywhere;
  word-break: break-word;
}

.rb-step-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  font-size: 22px;
  font-weight: 900;
  opacity: 0.8;
}

.rb-step-field div {
  font-size: 12px;
  line-height: 1.55;
  color: #1e293b;
  word-break: break-word;
}

.reasoningbank-exec {
  margin-top: 16px;
  background: linear-gradient(135deg, rgba(255,255,255,0.92), rgba(236,253,245,0.82));
  border: 1px solid var(--line);
  border-radius: 28px;
  padding: 18px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(12px);
}

.rb-exec-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 0.44fr);
  gap: 16px;
  align-items: stretch;
}

.rb-exec-head h2 {
  margin: 0;
  font-size: clamp(22px, 3vw, 34px);
  line-height: 1.08;
  letter-spacing: -0.04em;
  color: #0f172a;
}

.rb-exec-head p {
  margin: 10px 0 0;
  color: #475569;
  font-size: 14px;
  line-height: 1.7;
}

.rb-exec-metrics {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}

.rb-exec-metrics div,
.rb-exec-card {
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.88);
  padding: 12px;
}

.rb-exec-metrics b {
  display: block;
  font-size: 22px;
  line-height: 1.1;
  color: #0f172a;
}

.rb-exec-metrics span,
.rb-exec-card span {
  display: block;
  margin-top: 4px;
  color: var(--muted);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.rb-exec-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.rb-exec-card strong {
  display: block;
  margin-top: 8px;
  font-size: 16px;
  line-height: 1.35;
  color: #0f172a;
}

.rb-exec-card p {
  margin: 8px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: #1e293b;
}

.rb-exec-card em {
  display: block;
  margin-top: 8px;
  color: #0f766e;
  font-size: 12px;
  line-height: 1.5;
  font-style: normal;
  font-weight: 800;
}

.rb-chain {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.rb-chain-item {
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 18px;
  background: rgba(15, 23, 42, 0.04);
  padding: 12px;
}

.rb-chain-item span,
.rb-chain-item em {
  display: block;
  color: var(--muted);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  font-style: normal;
}

.rb-chain-item b,
.rb-chain-item code {
  display: block;
  margin-top: 5px;
  color: #0f172a;
  overflow-wrap: anywhere;
}

.rb-chain-item code {
  font-size: 12px;
  line-height: 1.45;
  color: #0f766e;
}

.rb-prepolicy-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin: 12px 0;
}

.rb-prepolicy-card {
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(240, 253, 250, 0.96), rgba(255, 255, 255, 0.96));
  padding: 13px;
}

.rb-prepolicy-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
  flex-wrap: wrap;
}

.rb-prepolicy-head strong {
  display: block;
  font-size: 15px;
  line-height: 1.35;
  font-weight: 900;
  color: #0f172a;
}

.rb-prepolicy-note {
  margin: 8px 0 0;
  color: #0f766e;
  font-size: 12px;
  line-height: 1.55;
  font-weight: 800;
}

.rb-module-io {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
  margin-top: 10px;
}

.rb-module-io > div {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 14px;
  background: rgba(255,255,255,0.86);
  padding: 9px 10px;
}

.rb-module-io span,
.rb-score-list b {
  display: block;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 900;
  color: var(--muted);
  margin-bottom: 4px;
}

.rb-module-io p {
  margin: 0;
  color: #1e293b;
  font-size: 12px;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.rb-score-list {
  display: grid;
  grid-template-columns: 1fr;
  gap: 7px;
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
}

.rb-score-list:empty {
  display: none;
}

.rb-score-list li {
  display: grid;
  grid-template-columns: 58px 48px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  border: 1px dashed rgba(15, 23, 42, 0.14);
  border-radius: 13px;
  background: rgba(255,255,255,0.72);
  padding: 8px 9px;
}

.rb-score-list b,
.rb-score-list span,
.rb-score-list em {
  margin: 0;
  color: #334155;
  font-size: 12px;
  line-height: 1.45;
  font-style: normal;
  overflow-wrap: anywhere;
}

.rb-score-list span {
  color: #0f766e;
  font-weight: 900;
}

.rb-module-flow-note {
  margin: 8px 0 12px;
  border: 1px dashed rgba(15, 23, 42, 0.16);
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.86);
  padding: 10px 12px;
  color: #475569;
  font-size: 12px;
  line-height: 1.6;
}

.rb-module-flow-note b {
  color: #0f766e;
}

.rb-episode-stack {
  gap: 16px;
}

.rb-episode-card {
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.92);
  padding: 16px;
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.06);
}

.rb-episode-memory-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.rb-episode-memory-card,
.rb-append-card,
.rb-empty-state {
  min-width: 0;
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 18px;
  background: linear-gradient(180deg, #fff, #f8fafc);
  padding: 12px;
}

.rb-episode-memory-card.is-compact {
  padding: 10px;
}

.rb-episode-memory-card.is-highlighted,
.rb-append-card {
  border-color: rgba(20, 184, 166, 0.35);
  background: linear-gradient(180deg, #ecfdf5, #ffffff);
}

.rb-memory-card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.rb-episode-memory-card strong,
.rb-append-card strong {
  display: block;
  font-size: 13px;
  line-height: 1.4;
  font-weight: 900;
  color: #0f172a;
}

.rb-episode-memory-card p,
.rb-append-card p,
.rb-episode-memory-card div,
.rb-append-card div,
.rb-append-card small,
.rb-empty-state {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: #334155;
  overflow-wrap: anywhere;
}

.rb-episode-memory-card.is-compact div {
  display: none;
}

.rb-inline-memory-list {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
}

.rb-trajectory-list {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.rb-trajectory-list li,
.rb-trajectory-empty {
  border: 1px dashed rgba(15, 23, 42, 0.14);
  border-radius: 14px;
  background: #f8fafc;
  padding: 9px 10px;
}

.rb-trajectory-list b,
.rb-trajectory-list span,
.rb-trajectory-list em,
.rb-trajectory-empty {
  display: block;
  font-size: 12px;
  line-height: 1.45;
  color: #334155;
  font-style: normal;
  overflow-wrap: anywhere;
}

.rb-trajectory-list b {
  color: #0f172a;
}

.rb-inline-memory-list .rb-episode-memory-card {
  box-shadow: none;
  padding: 10px;
}

.rb-candidate-list {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.rb-candidate-list li {
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 14px;
  background: #f8fafc;
  padding: 9px 10px;
}

.rb-candidate-list li.is-selected {
  border-color: rgba(20, 184, 166, 0.38);
  background: #ecfdf5;
}

.rb-candidate-list b,
.rb-candidate-list span,
.rb-candidate-list em {
  display: block;
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.rb-candidate-list b {
  color: #0f172a;
  font-weight: 900;
}

.rb-candidate-list em {
  color: var(--muted);
  font-style: normal;
}

.rb-bank-readonly {
  background: #f8fafc;
}

.rb-post-grid,
.rb-append-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.rb-consolidation-block {
  margin-top: 14px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 20px;
  background: rgba(248, 250, 252, 0.82);
  padding: 14px;
}

.rb-bank-after {
  margin-top: 12px;
  border-top: 1px dashed rgba(15, 23, 42, 0.12);
  padding-top: 12px;
}

.rb-memory-checkpoint {
  margin: 12px 0 18px;
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 20px;
  background: linear-gradient(180deg, rgba(248,250,252,0.98), rgba(255,255,255,0.95));
  padding: 14px;
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.04);
}

.rb-memory-checkpoint-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.rb-memory-checkpoint-title {
  margin-top: 4px;
  font-size: 15px;
  line-height: 1.35;
  font-weight: 900;
  color: #0f172a;
}

.rb-memory-checkpoint-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 10px;
}

.rb-memory-checkpoint-box {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 16px;
  background: white;
  padding: 12px;
}

.rb-memory-checkpoint-box span {
  display: block;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 6px;
}

.rb-memory-checkpoint-box strong {
  display: block;
  font-size: 14px;
  line-height: 1.4;
  color: #0f172a;
}

.rb-memory-checkpoint-box p {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: #1e293b;
  overflow-wrap: anywhere;
}

.rb-memory-checkpoint-content {
  color: var(--muted);
}

.rb-memory-checkpoint-list {
  margin: 0;
  padding-left: 18px;
}

.rb-memory-checkpoint-list li {
  margin: 0 0 8px;
  font-size: 12px;
  line-height: 1.55;
  color: #1e293b;
  white-space: normal;
}

.rb-memory-checkpoint-list li.is-new b {
  background: #d1fae5;
  padding: 2px 6px;
  border-radius: 999px;
}

.rb-bank-list {
  margin: 0;
  padding-left: 18px;
}

.rb-bank-list li {
  margin: 0 0 8px;
  font-size: 12px;
  line-height: 1.55;
  color: #1e293b;
  white-space: normal;
  overflow-wrap: anywhere;
}

.rb-bank-list li.is-new {
  padding: 8px 10px;
  margin-left: -10px;
  margin-right: -6px;
  border-radius: 12px;
  background: rgba(217, 249, 157, 0.26);
  border: 1px solid rgba(132, 204, 22, 0.25);
}

.rb-bank-list b {
  color: #0f172a;
  display: inline-block;
  margin-right: 6px;
}

.rb-bank-list span {
  display: inline;
}

.reasoningbank-page .reasoningbank-summary-layout {
  grid-template-columns: minmax(440px, 0.98fr) minmax(320px, 0.72fr);
}

.reasoningbank-summary-card {
  margin-top: 0;
}

.reasoningbank-summary-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.reasoningbank-step-list {
  margin-top: 16px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid var(--line);
  border-radius: 28px;
  padding: 18px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(12px);
}

.reasoningbank-method-map {
  margin-top: 16px;
  background: rgba(255, 255, 255, 0.74);
  border: 1px solid var(--line);
  border-radius: 28px;
  padding: 18px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(12px);
}

.rb-phase-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 10px;
}

.rb-phase-card {
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.92);
  padding: 14px;
}

.rb-phase-top,
.rb-schema-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.rb-phase-kicker {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 900;
  color: var(--muted);
}

.rb-phase-title {
  margin-top: 8px;
  font-size: 15px;
  font-weight: 900;
  line-height: 1.35;
  color: #0f172a;
}

.rb-phase-io {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-top: 10px;
}

.rb-phase-io span,
.rb-schema-grid span {
  display: inline-block;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 4px;
}

.rb-phase-io p,
.rb-schema-grid p {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: #1e293b;
}

.rb-phase-note {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--muted);
}

.rb-schema-card {
  margin-top: 12px;
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 20px;
  background: rgba(248, 250, 252, 0.95);
  padding: 14px;
}

.rb-schema-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 10px;
}

.rb-schema-grid > div {
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 16px;
  background: white;
  padding: 12px;
}

.rb-step-row {
  display: block;
  width: 100%;
}

.rb-step-row + .rb-step-row {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(15, 23, 42, 0.08);
}

.rb-step-media {
  position: sticky;
  top: 16px;
  align-self: start;
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.92);
  padding: 12px;
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.06);
}

.rb-step-media-head,
.rb-step-media-caption {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.rb-step-media-caption {
  margin-top: 8px;
}

.rb-step-frame {
  margin-top: 10px;
  overflow: hidden;
  border-radius: 16px;
  border: 1px solid rgba(15, 23, 42, 0.10);
  background: white;
}

.rb-step-image,
.rb-step-iframe {
  width: 100%;
  display: block;
}

.rb-step-iframe {
  min-height: 620px;
  border: 0;
}

.rb-step-body {
  border: 1px solid rgba(15, 23, 42, 0.10);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.90);
  padding: 14px;
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.05);
  margin-top: 10px;
}

.rb-step-summary {
  display: grid;
  grid-template-columns: 1fr 1fr 1.5fr;
  gap: 10px;
  margin-bottom: 12px;
}

.rb-step-summary-item {
  border: 1px solid rgba(15, 23, 42, 0.09);
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.95);
  padding: 10px 12px;
}

.rb-step-summary-item span {
  display: block;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 800;
  color: var(--muted);
  margin-bottom: 4px;
}

.rb-step-summary-item b,
.rb-step-summary-item div {
  font-size: 12px;
  line-height: 1.55;
  color: #0f172a;
  word-break: break-word;
}

.reasoningbank-page .raw-step-grid {
  grid-template-columns: 1fr;
}

.reasoningbank-page .raw-step-column {
  min-width: 0;
}

.reasoningbank-page .raw-step-column + .raw-step-column {
  margin-top: 8px;
}

.reasoningbank-page .raw-file,
.reasoningbank-page .raw-file-collapsible {
  min-width: 0;
}

.step-snapshot-sheet {
  width: 100%;
}

.step-snapshot-head {
  display: flex;
  gap: 16px;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.step-snapshot-layout {
  display: grid;
  grid-template-columns: minmax(500px, 1.15fr) minmax(280px, 0.75fr);
  gap: 14px;
  align-items: start;
}

.step-snapshot-copy {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.step-snapshot-img,
.step-snapshot-iframe {
  width: 100%;
  display: block;
}

.step-snapshot-iframe {
  min-height: 760px;
  border: 0;
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
  .pipeline-io { grid-template-columns: 1fr; }
  .raw-output-grid { grid-template-columns: 1fr; }
  .raw-step-grid { grid-template-columns: 1fr; }
  .step-snapshot-layout { grid-template-columns: 1fr; }
  .step-snapshot-head { flex-direction: column; }
  .rb-exec-head { grid-template-columns: 1fr; }
  .rb-exec-grid { grid-template-columns: 1fr; }
  .rb-chain { grid-template-columns: 1fr; }
  .rb-prepolicy-grid { grid-template-columns: 1fr; }
  .rb-score-list li { grid-template-columns: 1fr; }
  .rb-step-row { grid-template-columns: 1fr; }
  .rb-step-media { position: static; }
  .rb-step-summary { grid-template-columns: 1fr; }
  .reasoningbank-page .reasoningbank-summary-layout { grid-template-columns: 1fr; }
  .rb-bank-summary { grid-template-columns: 1fr; }
  .rb-bank-ribbon { grid-template-columns: 1fr; }
  .rb-bank-delta { grid-template-columns: 1fr; }
  .rb-step-io-grid { grid-template-columns: 1fr; }
  .rb-step-arrow { display: none; }
  .rb-step-topline { flex-direction: column; }
  .rb-explain-flow { grid-template-columns: 1fr; }
  .rb-explain-arrow { display: none; }
  .rb-step-panel-grid { grid-template-columns: 1fr; }
  .rb-step-memory-grid { grid-template-columns: 1fr; }
  .rb-memory-checkpoint-grid { grid-template-columns: 1fr; }
  .rb-phase-grid { grid-template-columns: 1fr; }
  .rb-phase-io { grid-template-columns: 1fr; }
  .rb-schema-grid { grid-template-columns: 1fr; }
  .rb-bank-grid { grid-template-columns: 1fr; }
  .rb-episode-memory-grid { grid-template-columns: 1fr; }
  .rb-post-grid { grid-template-columns: 1fr; }
  .rb-append-grid { grid-template-columns: 1fr; }
  .raw-file-collapsible summary { flex-direction: column; align-items: flex-start; }
  .raw-file-preview { text-align: left; white-space: normal; }
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
    if (
        len(groups) == 1
        and len(groups[0].get("bundles", [])) == 1
        and str(groups[0]["bundles"][0].get("metadata", {}).get("baseline") or "").strip() == "reasoningbank"
    ):
        out.write_text(render_reasoningbank_page(groups[0]["bundles"][0], compare_root), encoding="utf-8")
    else:
        out.write_text(render_compare_page(compare_root, groups), encoding="utf-8")
    print(out)
    if args.open:
        subprocess.run(["open", str(out)], check=False)


if __name__ == "__main__":
    main()
