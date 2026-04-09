"""
viz_io.py — Web Agent I/O Flow Viewer
각 스텝의 입력(IN) → 추론 → 출력(OUT) 흐름을 시각화

사용법:
  python viz_io.py <task_폴더>
  python viz_io.py eval_results/korail_dry_20260323_141643/taskktx_0
"""

import base64
import json
import re
import sys
from pathlib import Path


# ── 파서들 ───────────────────────────────────────────────────────────────────

def extract_tag(text, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return m.group(1).strip() if m else ""

def parse_user_prompt(text):
    """user_prompt.txt에서 섹션별로 추출"""
    return {
        "history":       extract_tag(text, "agent_history"),
        "user_request":  extract_tag(text, "user_request"),
        "file_system":   extract_tag(text, "file_system"),
        "todo":          extract_tag(text, "todo_contents"),
        "plan":          extract_tag(text, "plan"),
        "step_info":     extract_tag(text, "step_info"),
        "browser_state": extract_tag(text, "browser_state"),
    }

def parse_browser_state(bs_text):
    """browser_state에서 URL, page_stats, scroll info만 추출 (elements 제외)"""
    stats  = extract_tag(bs_text, "page_stats")
    url_m  = re.search(r"Current tab: \S+\nAvailable tabs:\nTab \S+: (\S+)", bs_text)
    url    = url_m.group(1) if url_m else ""
    page_m = re.search(r"(<page_info>.*?</page_info>)", bs_text)
    page_i = page_m.group(1).replace("<page_info>","").replace("</page_info>","").strip() if page_m else ""
    return {"url": url, "stats": stats, "page_info": page_i}

def parse_metadata(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def format_raw(raw: str) -> str:
    """raw LLM output 문자열을 key=value 단위로 줄바꿈해서 보기 좋게 포매팅"""
    # 알려진 키 목록 (등장 순서대로)
    keys = [
        "completion=",
        r"thinking=(?!None)",   # thinking= (None 제외)
        "evaluation_previous_goal=",
        "memory=",
        "next_goal=",
        "current_plan_item=",
        "plan_update=",
        "action=",
        r"thinking=None",
        "redacted_thinking=",
        "usage=",
        "stop_reason=",
    ]
    pattern = "(" + "|".join(keys) + ")"
    parts = re.split(pattern, raw)
    lines = []
    i = 0
    while i < len(parts):
        p = parts[i]
        if re.fullmatch(pattern, p):
            # 키 + 다음 값 합치기
            val = parts[i+1] if i+1 < len(parts) else ""
            lines.append(p + val)
            i += 2
        else:
            if p.strip():
                lines.append(p.strip())
            i += 1
    return "\n\n".join(lines)


def parse_llm_output(path):
    """llm_output.json raw 문자열에서 thinking / plan_update / current_plan_item 추출.
    JudgementResult면 is_judge=True로 반환."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("raw", "")
    except Exception:
        return {}
    result = {"raw": raw}

    # Judge 스텝 감지
    if "JudgementResult(" in raw:
        m_reason  = re.search(r"reasoning='((?:[^'\\]|\\.)*)'", raw)
        m_verdict = re.search(r"verdict=(True|False)", raw)
        m_fail    = re.search(r"failure_reason='((?:[^'\\]|\\.)*)'", raw)
        result.update({
            "is_judge":      True,
            "reasoning":     m_reason.group(1)  if m_reason  else "",
            "verdict":       m_verdict.group(1) if m_verdict else "",
            "failure_reason":m_fail.group(1)    if m_fail    else "",
        })
        return result

    result["is_judge"] = False

    def extract_str(key):
        # key="..." 또는 key='...'  (이스케이프 포함)
        for q in ('"', "'"):
            m = re.search(rf'{key}={q}((?:[^{q}\\]|\\.)*?){q}', raw)
            if m:
                return m.group(1).replace("\\n", "\n").replace("\\'", "'").replace('\\"', '"')
        return ""

    thinking = extract_str("thinking")

    # plan_update=['...', '...']
    plan_update = []
    m = re.search(r"plan_update=(\[.*?\])", raw, re.DOTALL)
    if m:
        items = re.findall(r"['\"](.+?)['\"]", m.group(1))
        plan_update = items

    # current_plan_item=N
    m2 = re.search(r"current_plan_item=(\d+)", raw)
    current_plan_item = int(m2.group(1)) if m2 else None

    result.update({
        "thinking":          thinking,
        "plan_update":       plan_update,
        "current_plan_item": current_plan_item,
    })
    return result

def parse_history_steps(history_text):
    """agent_history 안의 <step> 블록들 추출.
    browser-use는 <step>을 여는 태그로만 씀 (닫는 태그 없음) → split으로 파싱"""
    # <step>을 구분자로 분리, 첫 조각(Agent initialized 등)은 별도 보존
    parts = re.split(r"<step>", history_text)
    result = []
    for p in parts:
        p = p.strip()
        if p:
            result.append(p)
    return result


# ── HTML 컴포넌트 ─────────────────────────────────────────────────────────────

def esc(s):
    return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def section(icon, label, content_html, color="#f8fafc", border="#e2e8f0", collapsible=False, collapsed=False):
    if not content_html:
        return ""
    uid = f"sec_{id(content_html)}"
    if collapsible:
        toggle = f'onclick="toggleSec(\'{uid}\')"'
        arrow_id = f'arr_{uid}'
        body_style = "display:none;" if collapsed else ""
        arrow_rot = "transform:rotate(-90deg);" if collapsed else ""
        return f"""
<div class="io-section" style="border-color:{border};background:{color}">
  <div class="io-sec-header" {toggle} style="cursor:pointer;user-select:none">
    <span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#64748b">{icon} {label}</span>
    <svg id="{arrow_id}" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2.5"
         style="transition:transform .2s;{arrow_rot}"><polyline points="6 9 12 15 18 9"/></svg>
  </div>
  <div id="{uid}" style="{body_style}margin-top:10px">{content_html}</div>
</div>"""
    else:
        return f"""
<div class="io-section" style="border-color:{border};background:{color}">
  <div class="io-sec-header">
    <span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#64748b">{icon} {label}</span>
  </div>
  <div style="margin-top:10px">{content_html}</div>
</div>"""

def pre(text):
    return f'<pre class="mono">{esc(text)}</pre>'

def chip(text, bg="#f1f5f9", fg="#475569"):
    return f'<span style="background:{bg};color:{fg};padding:3px 9px;border-radius:4px;font-size:12px;display:inline-block;margin:2px 2px 2px 0">{esc(text)}</span>'

def action_badge(action_str):
    # action 문자열에서 종류 추출
    m = re.search(r"(\w+ActionModel)", action_str)
    kind = m.group(1).replace("ActionModel","") if m else "Action"
    colors = {
        "Click":    ("#dbeafe","#1d4ed8"),
        "Type":     ("#fef9c3","#92400e"),
        "Navigate": ("#ede9fe","#6d28d9"),
        "Scroll":   ("#f0fdf4","#15803d"),
        "Done":     ("#dcfce7","#15803d"),
        "Wait":     ("#f1f5f9","#475569"),
        "Extract":  ("#fff7ed","#c2410c"),
    }
    bg, fg = colors.get(kind, ("#f1f5f9","#334155"))
    return f'<span style="background:{bg};color:{fg};padding:3px 9px;border-radius:4px;font-size:12px;font-weight:600;font-family:monospace">{kind}</span>'


# ── 스텝 HTML 생성 ────────────────────────────────────────────────────────────

def build_step_s0(task_text: str, history_text: str) -> str:
    """S0 — LLM 없는 자동 초기화 스텝 섹션"""
    # URL 추출
    url_m = re.search(r"https?://\S+", task_text)
    auto_url = url_m.group(0).rstrip(".,)") if url_m else "(URL 없음)"

    # history에서 S0 결과 메시지 추출 (첫 <step> 이전 + 첫 <step> 내용)
    parts = re.split(r"<step>", history_text)
    init_msg  = parts[0].strip() if parts else ""          # "Agent initialized"
    step0_msg = parts[1].strip() if len(parts) > 1 else "" # "Result\nFound initial url..."

    return f"""
<section id="S0" class="step-wrap">
  <div class="step-title">
    <span class="step-num" style="background:#b45309">S0</span>
    <span class="step-goal">자동 초기화 — LLM 호출 없음</span>
    <span style="font-size:11px;background:#fef3c7;color:#92400e;padding:3px 8px;border-radius:4px;font-weight:600">⚡ Auto</span>
  </div>

  <div style="display:grid;grid-template-columns:1fr 44px 1fr;gap:0;align-items:start">

    <!-- 입력 -->
    <div class="io-col">
      <div class="io-col-header in-header">INPUT</div>
      <div class="io-section" style="border-color:#fde68a;background:#fffbeb">
        <div class="io-sec-header"><span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#92400e">📋 Task 텍스트 (URL 추출 대상)</span></div>
        <div style="margin-top:10px">
          <pre class="mono">{esc(task_text)}</pre>
        </div>
      </div>
    </div>

    <!-- 구분선 -->
    <div class="io-arrow">
      <div class="arrow-line"></div>
      <div class="arrow-label" style="background:#fef3c7;color:#92400e">_extract<br>_start<br>_url()</div>
      <div class="arrow-line"></div>
    </div>

    <!-- 출력 -->
    <div class="io-col">
      <div class="io-col-header" style="background:#b45309;color:white;font-size:10px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;padding:6px 12px;border-radius:6px;margin-bottom:4px;text-align:center">AUTO OUTPUT</div>

      <div class="io-section" style="border-color:#fde68a;background:#fffbeb">
        <div class="io-sec-header"><span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#92400e">🔗 추출된 URL</span></div>
        <div style="margin-top:10px">
          <code style="font-size:13px;font-weight:600;color:#1d4ed8;background:#eff6ff;padding:4px 10px;border-radius:6px;word-break:break-all">{esc(auto_url)}</code>
        </div>
      </div>

      <div class="io-section" style="border-color:#fde68a;background:#fffbeb">
        <div class="io-sec-header"><span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#92400e">🤖 자동 실행 액션</span></div>
        <div style="margin-top:10px">
          <span style="background:#dbeafe;color:#1d4ed8;padding:3px 9px;border-radius:4px;font-size:12px;font-weight:600;font-family:monospace">Navigate</span>
          <code style="margin-left:8px;font-size:12px;color:#475569">{esc(auto_url)}</code>
        </div>
      </div>

      <div class="io-section" style="border-color:#fde68a;background:#fffbeb">
        <div class="io-sec-header"><span style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#92400e">📜 agent_history에 기록되는 내용</span></div>
        <div style="margin-top:10px">
          <pre class="mono">{esc(init_msg)}
&lt;step&gt;
{esc(step0_msg)}</pre>
          <p style="font-size:11px;color:#92400e;margin-top:8px">→ S1부터의 모든 스텝 INPUT의 🕓 Agent History 맨 앞에 이 내용이 들어감</p>
        </div>
      </div>

    </div>
  </div>
</section>
"""


def build_step(step_num, prompt, meta, llm, img_b64, system_prompt_html):
    # ── Judge 스텝이면 별도 렌더링 ───────────────────────────────────
    if llm.get("is_judge"):
        verdict     = llm.get("verdict","")
        reasoning   = llm.get("reasoning","")
        fail_reason = llm.get("failure_reason","")
        raw_text    = llm.get("raw","")
        verdict_ok  = verdict == "True"
        v_bg  = "#f0fdf4" if verdict_ok else "#fef2f2"
        v_bdr = "#86efac" if verdict_ok else "#fca5a5"
        v_icon= "✅" if verdict_ok else "❌"
        v_txt = "PASS" if verdict_ok else "FAIL"
        v_col = "#15803d" if verdict_ok else "#b91c1c"
        return f"""
<section id="S{step_num}" class="step-wrap">
  <div class="step-title">
    <span class="step-num" style="background:#7c3aed">S{step_num}</span>
    <span class="step-goal">⚖️ Judge Evaluation (별도 LLM 호출 — 에이전트 스텝 아님)</span>
    <span style="font-size:13px;font-weight:700;background:{v_bg};color:{v_col};padding:4px 12px;border-radius:6px;border:1px solid {v_bdr}">{v_icon} {v_txt}</span>
  </div>
  <div style="background:white;border:1px solid {v_bdr};border-radius:10px;padding:16px;margin-bottom:12px">
    <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#7c3aed;margin-bottom:8px">⚖️ Verdict: {v_txt}</div>
    <p style="font-size:13px;line-height:1.7;color:#1e293b">{esc(reasoning)}</p>
    {f'<p style="margin-top:8px;font-size:13px;color:#b91c1c"><strong>Failure:</strong> {esc(fail_reason)}</p>' if fail_reason else ""}
  </div>
  {section("📄", "Raw Judge Output", pre(format_raw(raw_text)), color="#fafaf9", border="#e2e8f0", collapsible=True, collapsed=True)}
</section>
"""

    bs  = parse_browser_state(prompt.get("browser_state",""))
    hist_steps = parse_history_steps(prompt.get("history",""))

    # ── [IN] 섹션들 ──────────────────────────────────────────────────

    # system prompt (접기 가능, 기본 접힘)
    in_system = section("⚙️", "System Prompt",
        pre(system_prompt_html),
        color="#fafaf9", border="#e7e5e4",
        collapsible=True, collapsed=True)

    # task
    task_text = prompt.get("user_request","").strip()
    in_task = section("📋", "Task (User Request)",
        f'<p style="font-size:14px;line-height:1.7;color:#1e293b;white-space:pre-wrap">{esc(task_text)}</p>',
        color="#eff6ff", border="#bfdbfe",
        collapsible=True, collapsed=True)

    # agent history
    if hist_steps:
        hist_html = ""
        for i, s in enumerate(hist_steps, 1):
            hist_html += f'<div style="margin-bottom:8px"><span style="font-size:10px;font-weight:700;color:#94a3b8;font-family:monospace">STEP {i}</span><pre class="mono" style="margin-top:4px">{esc(s)}</pre></div>'
        in_hist = section("🕓", f"Agent History ({len(hist_steps)} steps)",
            hist_html, color="#fafaf9", border="#e7e5e4",
            collapsible=True, collapsed=(len(hist_steps) > 3))
    else:
        in_hist = section("🕓", "Agent History", '<span style="color:#94a3b8;font-size:13px">첫 번째 스텝</span>')

    # plan — 마커별 색상 배지로 렌더링
    plan_text = prompt.get("plan","").strip()
    if plan_text:
        marker_cfg = {
            "[>]": ("▶ 진행중", "#fef3c7", "#92400e"),
            "[x]": ("✓ 완료",  "#dcfce7", "#15803d"),
            "[-]": ("- 스킵",  "#f1f5f9", "#94a3b8"),
            "[ ]": ("○ 대기",  "#f8fafc", "#64748b"),
        }
        plan_rows = ""
        for line in plan_text.splitlines():
            line = line.strip()
            if not line:
                continue
            matched = False
            for marker, (label, bg, fg) in marker_cfg.items():
                if line.startswith(marker):
                    rest = esc(line[len(marker):].strip())
                    plan_rows += (
                        f'<div style="display:flex;align-items:center;gap:8px;'
                        f'padding:6px 0;border-bottom:1px solid #f1f5f9">'
                        f'<span style="background:{bg};color:{fg};padding:2px 7px;'
                        f'border-radius:4px;font-size:11px;font-weight:700;'
                        f'white-space:nowrap;font-family:monospace">{label}</span>'
                        f'<span style="font-size:13px;color:#1e293b">{rest}</span>'
                        f'</div>'
                    )
                    matched = True
                    break
            if not matched:
                plan_rows += f'<div style="font-size:12px;color:#94a3b8;padding:3px 0">{esc(line)}</div>'
        in_plan = section("📝", "Current Plan", plan_rows,
            color="#fafaf9", border="#e7e5e4", collapsible=True, collapsed=False)
    else:
        in_plan = ""

    # browser state 요약
    bs_html = ""
    if bs["url"]:
        bs_html += f'<div style="margin-bottom:6px"><span class="label-sm">URL</span> <code style="font-size:12px;background:#f1f5f9;padding:2px 6px;border-radius:4px">{esc(bs["url"])}</code></div>'
    if bs["stats"]:
        bs_html += f'<div style="margin-bottom:6px"><span class="label-sm">PAGE STATS</span> <span style="font-size:13px;color:#475569">{esc(bs["stats"])}</span></div>'
    if bs["page_info"]:
        bs_html += f'<div><span class="label-sm">SCROLL</span> <span style="font-size:13px;color:#475569">{esc(bs["page_info"])}</span></div>'
    in_browser = section("🌐", "Browser State", bs_html, color="#f0fdf4", border="#bbf7d0") if bs_html else ""

    # screenshot
    if img_b64:
        img_html = f'<img src="data:image/png;base64,{img_b64}" style="width:100%;border-radius:8px;border:1px solid #e2e8f0;display:block"/>'
    else:
        img_html = '<div style="aspect-ratio:16/9;background:#f8fafc;border:2px dashed #cbd5e1;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:13px">스크린샷 없음</div>'
    in_screenshot = section("🖼️", "SoM Screenshot (browser-use 입력 이미지)", img_html, color="white", border="#e2e8f0")

    # ── [OUT] 섹션들 (metadata.json + llm_output.json) ───────────────

    eval_text = meta.get("evaluation_previous_goal","").strip()
    mem_text  = meta.get("memory","").strip()
    goal_text = meta.get("next_goal","").strip()
    action_raw= meta.get("action","").strip()
    elapsed   = meta.get("elapsed_sec","")

    thinking_text    = llm.get("thinking","").strip()
    plan_update      = llm.get("plan_update", [])
    current_plan_item= llm.get("current_plan_item")
    raw_text         = llm.get("raw","").strip()

    # raw output (접기, 기본 접힘)
    out_raw = section("📄", "Raw LLM Output",
        pre(format_raw(raw_text)),
        color="#fafaf9", border="#e2e8f0",
        collapsible=True, collapsed=True) if raw_text else ""

    # thinking (LLM 내부 추론)
    out_thinking = section("💭", "Thinking",
        pre(thinking_text),
        color="#fafaf9", border="#e7e5e4",
        collapsible=True, collapsed=False) if thinking_text else ""

    out_eval = section("✅", "Evaluation of Previous Goal",
        f'<p style="font-size:13px;line-height:1.65;color:#1e293b">{esc(eval_text)}</p>',
        color="#f0fdf4", border="#bbf7d0") if eval_text else ""

    out_mem = section("🧠", "Memory",
        f'<p style="font-size:13px;line-height:1.65;color:#1e293b">{esc(mem_text)}</p>',
        color="#eff6ff", border="#bfdbfe") if mem_text else ""

    out_goal = section("🎯", "Next Goal",
        f'<p style="font-size:14px;font-weight:600;color:#1e293b">{esc(goal_text)}</p>',
        color="#fefce8", border="#fde68a") if goal_text else ""

    # plan_update (이 스텝에서 새로 생성/갱신한 플랜)
    if plan_update:
        items_html = "".join(
            f'<div style="display:flex;align-items:flex-start;gap:8px;padding:5px 0;border-bottom:1px solid #f1f5f9">'
            f'<span style="font-size:11px;font-weight:700;font-family:monospace;color:#94a3b8;min-width:20px">{i}</span>'
            f'<span style="font-size:13px;color:#1e293b">{esc(item)}</span>'
            f'</div>'
            for i, item in enumerate(plan_update)
        )
        cpi_note = f'<div style="margin-bottom:8px;font-size:12px;color:#64748b">현재 실행 중: <code style="background:#fefce8;padding:2px 6px;border-radius:4px">item {current_plan_item}</code></div>' if current_plan_item is not None else ""
        out_plan = section("📝", "Plan Update (새로 생성된 플랜)",
            cpi_note + items_html,
            color="#fefce8", border="#fde68a")
    else:
        # plan_update는 없지만 current_plan_item은 표시
        if current_plan_item is not None:
            out_plan = section("📝", "Plan Progress",
                f'<span style="font-size:13px;color:#64748b">현재 실행 중: <code style="background:#fefce8;padding:2px 6px;border-radius:4px">item {current_plan_item}</code></span>',
                color="#fafaf9", border="#e7e5e4")
        else:
            out_plan = ""

    if action_raw:
        action_lines = [l.strip() for l in action_raw.split("\n") if l.strip()]
        # DoneAction이면 답변 텍스트 별도 추출
        done_text = ""
        if "DoneAction" in action_raw:
            m = re.search(r"text='((?:[^'\\]|\\.)*)'", action_raw)
            if not m:
                m = re.search(r'text="((?:[^"\\]|\\.)*)"', action_raw)
            if m:
                done_text = m.group(1).replace("\\n", "\n")
        action_html = "".join(
            f'<div style="margin-bottom:6px">{action_badge(l)}'
            f'<pre class="mono" style="display:inline;margin-left:8px;font-size:12px;color:#475569">{esc(l)}</pre></div>'
            for l in action_lines
        )
        if done_text:
            action_html += f'<div style="margin-top:12px;background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:12px 14px"><div style="font-size:10px;font-weight:700;color:#15803d;margin-bottom:6px;text-transform:uppercase;letter-spacing:.08em">📢 Final Answer</div><pre class="mono" style="color:#14532d">{esc(done_text)}</pre></div>'
        out_action = section("🤖", f"Action ({len(action_lines)}개)",
            action_html, color="#fdf4ff", border="#e9d5ff")
    else:
        out_action = ""

    elapsed_html = f'<span style="font-size:12px;color:#94a3b8">⏱ {elapsed}s</span>' if elapsed else ""

    return f"""
<section id="S{step_num}" class="step-wrap">

  <div class="step-title">
    <span class="step-num">S{step_num}</span>
    <span class="step-goal">{esc(goal_text) or "—"}</span>
    {elapsed_html}
  </div>

  <div class="io-flow">

    <!-- 입력단 -->
    <div class="io-col">
      <div class="io-col-header in-header">INPUT</div>
      {in_system}
      {in_task}
      {in_hist}
      {in_plan}
      {in_browser}
      {in_screenshot}
    </div>

    <!-- 구분선 -->
    <div class="io-arrow">
      <div class="arrow-line"></div>
      <div class="arrow-label">LLM</div>
      <div class="arrow-line"></div>
    </div>

    <!-- 출력단 -->
    <div class="io-col">
      <div class="io-col-header out-header">OUTPUT</div>
      {out_raw}
      {out_thinking}
      {out_eval}
      {out_mem}
      {out_goal}
      {out_plan}
      {out_action}
    </div>

  </div>
</section>
"""


# ── 전체 HTML ─────────────────────────────────────────────────────────────────

def build_html(task_dir, steps, system_prompt_text):
    task_name = task_dir.name

    sidebar_items = ""
    for s in steps:
        goal = esc(s["goal"][:45] + "…" if len(s["goal"]) > 45 else s["goal"]) or "—"
        done_mark = " ✓" if "done" in s["action"].lower() else ""
        is_s0 = s["num"] == "0"
        id_style = 'style="color:#fbbf24"' if is_s0 else ""
        sidebar_items += f"""
<a class="sb-item" href="#S{s['num']}" onclick="setActive(this)">
  <span class="sb-id" {id_style}>S{s['num']}{done_mark}</span>
  <span class="sb-goal">{goal}</span>
</a>"""

    sections_html = "\n".join(s["html"] for s in steps)

    legend_html = f"""
<section class="step-wrap" id="legend">
  <div class="step-title">
    <span class="step-num" style="background:#475569">?</span>
    <span class="step-goal" style="font-weight:600;color:#1e293b">시스템 구조 & 필드 설명</span>
  </div>

  <!-- 전체 흐름 -->
  <div style="background:#0f172a;border-radius:10px;padding:18px 20px;margin-bottom:16px;font-family:monospace;font-size:13px;line-height:2.2;color:#e2e8f0">
    <span style="color:#94a3b8;font-size:11px">① 시작</span><br>
    Task (자연어 질문)
    <span style="color:#64748b"> →</span>
    <span style="color:#93c5fd"> DRY_RUN_PROMPT</span>
    <span style="color:#64748b"> →</span>
    <span style="color:#86efac"> browser-use Agent.run()</span>
    <br><br>
    <span style="color:#94a3b8;font-size:11px">② S0 — LLM 호출 없는 자동 초기화 (agent_history에 기록됨)</span><br>
    <span style="color:#fbbf24">Agent initialized</span>
    <span style="color:#64748b"> →</span>
    task 텍스트에서 URL 자동 추출
    <span style="color:#64748b"> (_extract_start_url)</span>
    <span style="color:#64748b"> →</span>
    <span style="color:#fbbf24"> navigate(url)</span> 자동 실행
    <span style="color:#64748b"> →</span>
    <span style="color:#fbbf24"> "Found initial url and automatically loaded it."</span> history에 삽입
    <br><br>
    <span style="color:#94a3b8;font-size:11px">③ S1~SN — 반복 에이전트 루프 (LLM 호출마다 여기 뷰어의 스텝 1개)</span><br>
    <span style="color:#fde68a"> [Browser]</span> 스크린샷 + DOM
    <span style="color:#64748b"> →</span>
    <span style="color:#fde68a"> SoM 이미지</span> + 요소 목록
    <span style="color:#64748b"> →</span>
    <span style="color:#38bdf8"> [INPUT]</span> system + user_prompt (history·state·browser) + 이미지
    <span style="color:#64748b"> →</span>
    <span style="color:#c084fc"> LLM</span>
    <span style="color:#64748b"> →</span>
    <span style="color:#4ade80"> [OUTPUT]</span> AgentOutput
    <span style="color:#64748b"> →</span>
    액션 실행
    <span style="color:#64748b"> →</span> 결과를 history에 append
    <span style="color:#64748b"> →</span> 반복
  </div>

  <!-- S0 설명 박스 -->
  <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:14px 16px;margin-bottom:16px;font-size:13px;line-height:1.7">
    <div style="font-size:10px;font-weight:800;letter-spacing:.1em;color:#92400e;margin-bottom:8px">⚡ S0 — 자동 초기화 스텝 (LLM 미호출)</div>
    <p style="color:#78350f;margin-bottom:6px">
      <code style="background:#fef3c7;padding:2px 5px;border-radius:3px">Agent.__init__()</code> 시점에 browser-use가 task 텍스트를 정규식으로 스캔해서 URL을 찾으면
      (<code style="background:#fef3c7;padding:2px 5px;border-radius:3px">_extract_start_url()</code>),
      첫 LLM 호출 전에 <strong>자동으로 navigate 액션을 실행</strong>합니다.
    </p>
    <p style="color:#78350f;margin-bottom:6px">
      이 결과가 <code style="background:#fef3c7;padding:2px 5px;border-radius:3px">state.last_result</code>에 저장되고,
      S1의 <code style="background:#fef3c7;padding:2px 5px;border-radius:3px">agent_history</code>에 아래처럼 삽입됩니다:
    </p>
    <pre style="background:#fef3c7;border-radius:6px;padding:10px 12px;font-size:12px;color:#451a03;margin:0">Agent initialized          ← agent 생성 완료 메시지
&lt;step&gt;
Result
Found initial url and automatically loaded it.
Navigated to https://www.korail.com/ticket/main   ← S0 자동 navigate 결과</pre>
    <p style="color:#92400e;margin-top:8px;font-size:12px">
      → 따라서 S1의 🕓 Agent History에 이미 스텝이 2개 들어있는 것처럼 보이는 것. 실제로 LLM이 호출된 건 S1부터.
    </p>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">

    <!-- INPUT 필드 -->
    <div style="background:white;border:1px solid #bfdbfe;border-radius:10px;padding:16px">
      <div style="font-size:10px;font-weight:800;letter-spacing:.1em;color:#1d4ed8;margin-bottom:12px">INPUT 필드</div>
      <table style="width:100%;border-collapse:collapse;font-size:12px">
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:7px 8px;font-weight:700;font-family:monospace;color:#1d4ed8;white-space:nowrap">⚙️ System Prompt</td>
          <td style="padding:7px 8px;color:#475569">browser-use 프레임워크가 주입하는 고정 지시문. 출력 형식(AgentOutput), 브라우저 규칙, 플랜 작성 방법 등 정의. 매 스텝 동일.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:7px 8px;font-weight:700;font-family:monospace;color:#1d4ed8;white-space:nowrap">📋 Task</td>
          <td style="padding:7px 8px;color:#475569">eval_korail_run.py의 DRY_RUN_PROMPT로 만든 유저 요청. 목표 태스크 + 로그인 정보 + 주의사항. 매 스텝 동일하게 포함.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:7px 8px;font-weight:700;font-family:monospace;color:#1d4ed8;white-space:nowrap">🕓 Agent History</td>
          <td style="padding:7px 8px;color:#475569">이전 스텝들의 eval / memory / next_goal / action 결과를 순서대로 기록한 이벤트 스트림. LLM이 지금까지 뭘 했는지 파악하는 데 사용.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:7px 8px;font-weight:700;font-family:monospace;color:#1d4ed8;white-space:nowrap">📝 Plan</td>
          <td style="padding:7px 8px;color:#475569">LLM이 직접 작성한 할 일 목록. [>]=현재, [x]=완료, [ ]=미완. LLM이 plan_update를 출력하면 다음 스텝부터 반영됨.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:7px 8px;font-weight:700;font-family:monospace;color:#1d4ed8;white-space:nowrap">🌐 Browser State</td>
          <td style="padding:7px 8px;color:#475569">현재 URL, 탭 목록, 페이지 통계(링크/인터랙티브 요소 수), 스크롤 위치. 전체 DOM 트리도 포함되지만 여기선 요약만 표시.</td>
        </tr>
        <tr>
          <td style="padding:7px 8px;font-weight:700;font-family:monospace;color:#1d4ed8;white-space:nowrap">🖼️ SoM Screenshot</td>
          <td style="padding:7px 8px;color:#475569">Set-of-Mark 이미지. browser-use가 각 인터랙티브 요소에 번호 박스를 오버레이한 스크린샷. LLM의 시각 입력(vision input).</td>
        </tr>
      </table>
    </div>

    <!-- OUTPUT 필드 -->
    <div style="background:white;border:1px solid #bbf7d0;border-radius:10px;padding:16px">
      <div style="font-size:10px;font-weight:800;letter-spacing:.1em;color:#15803d;margin-bottom:12px">OUTPUT 필드 — AgentOutput</div>
      <table style="width:100%;border-collapse:collapse;font-size:12px">
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:7px 8px;font-weight:700;font-family:monospace;color:#15803d;white-space:nowrap">💭 Thinking</td>
          <td style="padding:7px 8px;color:#475569">LLM 내부 추론(chain-of-thought). 태스크 분석, 전략 수립 등. 복잡한 스텝에서만 등장. 출력에는 포함되지만 다음 스텝 입력으로는 전달 안 됨.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:7px 8px;font-weight:700;font-family:monospace;color:#15803d;white-space:nowrap">✅ Evaluation</td>
          <td style="padding:7px 8px;color:#475569">직전 스텝의 액션이 성공했는지 평가. 스크린샷 기준으로 판단. "Success / Failed / Uncertain" 형태. 다음 스텝 계획에 반영됨.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:7px 8px;font-weight:700;font-family:monospace;color:#15803d;white-space:nowrap">🧠 Memory</td>
          <td style="padding:7px 8px;color:#475569">현재 스텝에서 기억해 둘 핵심 사실. 다음 스텝의 agent_history에 포함돼 컨텍스트로 전달됨. 외부 메모리가 아닌 히스토리 내 텍스트.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:7px 8px;font-weight:700;font-family:monospace;color:#15803d;white-space:nowrap">🎯 Next Goal</td>
          <td style="padding:7px 8px;color:#475569">이번 스텝에서 달성할 구체적 목표. 사이드바에도 표시됨. 다음 스텝 히스토리에 기록돼 LLM이 맥락 추적하는 데 활용.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:7px 8px;font-weight:700;font-family:monospace;color:#15803d;white-space:nowrap">📝 Plan Update</td>
          <td style="padding:7px 8px;color:#475569">LLM이 플랜을 새로 작성하거나 수정할 때만 등장. 다음 스텝부터 &lt;plan&gt; 태그로 INPUT에 삽입됨. current_plan_item으로 진행 위치 추적.</td>
        </tr>
        <tr>
          <td style="padding:7px 8px;font-weight:700;font-family:monospace;color:#15803d;white-space:nowrap">🤖 Action</td>
          <td style="padding:7px 8px;color:#475569">실제로 실행할 브라우저 액션. Click(index), Type(text), Navigate(url), Scroll, Done(answer) 등. 한 스텝에 최대 3개까지 가능.</td>
        </tr>
      </table>
    </div>

  </div>

  <!-- System Prompt 상세 -->
  <div style="margin-top:16px;background:white;border:1px solid #e2e8f0;border-radius:10px;padding:16px">
    <div style="font-size:10px;font-weight:800;letter-spacing:.1em;color:#475569;margin-bottom:12px">⚙️ SYSTEM PROMPT 구조 (browser-use 프레임워크 주입, 매 스텝 동일)</div>

    <table style="width:100%;border-collapse:collapse;font-size:12px;margin-bottom:14px">
      <thead>
        <tr style="background:#f8fafc">
          <th style="padding:7px 10px;text-align:left;border-bottom:2px solid #e2e8f0;color:#64748b;font-weight:700;white-space:nowrap">태그</th>
          <th style="padding:7px 10px;text-align:left;border-bottom:2px solid #e2e8f0;color:#64748b;font-weight:700">역할</th>
          <th style="padding:7px 10px;text-align:left;border-bottom:2px solid #e2e8f0;color:#64748b;font-weight:700">핵심 내용</th>
        </tr>
      </thead>
      <tbody>
        <tr style="border-bottom:1px solid #f1f5f9"><td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">&lt;intro&gt;</td><td style="padding:7px 10px;color:#475569">에이전트 역할 정의</td><td style="padding:7px 10px;color:#64748b">브라우저 자동화 AI임을 선언. 웹 탐색·폼 제출·정보 수집 등 능력 명시.</td></tr>
        <tr style="border-bottom:1px solid #f1f5f9"><td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">&lt;language_settings&gt;</td><td style="padding:7px 10px;color:#475569">언어 설정</td><td style="padding:7px 10px;color:#64748b">기본 영어. user_request 언어로 응답. (태스크가 한국어면 한국어로 답)</td></tr>
        <tr style="border-bottom:1px solid #f1f5f9"><td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">&lt;input&gt;</td><td style="padding:7px 10px;color:#475569">입력 구조 설명</td><td style="padding:7px 10px;color:#64748b">매 스텝 입력이 agent_history / agent_state / browser_state / browser_vision / read_state로 구성됨을 설명.</td></tr>
        <tr style="border-bottom:1px solid #f1f5f9"><td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">&lt;browser_state&gt;</td><td style="padding:7px 10px;color:#475569">DOM 형식 설명</td><td style="padding:7px 10px;color:#64748b">[index]&lt;tag /&gt; 트리 형식 정의. *[=새 요소, |SCROLL|=스크롤 컨테이너, |SHADOW|=shadow DOM 설명.</td></tr>
        <tr style="border-bottom:1px solid #f1f5f9"><td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">&lt;browser_vision&gt;</td><td style="padding:7px 10px;color:#475569">스크린샷 활용</td><td style="padding:7px 10px;color:#64748b">SoM 이미지가 GROUND TRUTH. 텍스트 없는 요소는 이미지에서 index 번호로 확인.</td></tr>
        <tr style="border-bottom:1px solid #f1f5f9"><td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">&lt;browser_rules&gt;</td><td style="padding:7px 10px;color:#475569">브라우저 조작 규칙</td><td style="padding:7px 10px;color:#64748b">indexed 요소만 클릭 / CAPTCHA 자동 처리 / 팝업 먼저 닫기 / 같은 URL 3스텝 이상 = 루프 감지 / extract는 비싸니 신중하게 등 20여 개 규칙.</td></tr>
        <tr style="border-bottom:1px solid #f1f5f9"><td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">&lt;file_system&gt;</td><td style="padding:7px 10px;color:#475569">파일 시스템</td><td style="padding:7px 10px;color:#64748b">todo.md로 진행 추적. 10스텝 이하엔 사용 금지. 긴 태스크는 results.md에 저장.</td></tr>
        <tr style="border-bottom:1px solid #f1f5f9"><td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">&lt;planning&gt;</td><td style="padding:7px 10px;color:#475569">플랜 작성 규칙</td><td style="padding:7px 10px;color:#64748b">단순(1-3액션)=플랜 없음 / 복잡+명확=즉시 plan_update / 복잡+불명확=탐색 후 plan_update. [x]/[&gt;]/[ ]/[-] 마커.</td></tr>
        <tr style="border-bottom:1px solid #f1f5f9"><td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">&lt;task_completion_rules&gt;</td><td style="padding:7px 10px;color:#475569">done 액션 규칙</td><td style="padding:7px 10px;color:#64748b">완료 또는 max_steps 도달 시 done 호출. 호출 전 요건 체크리스트 6단계 검증 필수. done은 단독 액션.</td></tr>
        <tr style="border-bottom:1px solid #f1f5f9"><td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">&lt;action_rules&gt;</td><td style="padding:7px 10px;color:#475569">액션 수 제한</td><td style="padding:7px 10px;color:#64748b">스텝당 최대 3개 액션. 페이지 변경 시 나머지 자동 스킵.</td></tr>
        <tr style="border-bottom:1px solid #f1f5f9"><td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">&lt;efficiency_guidelines&gt;</td><td style="padding:7px 10px;color:#475569">효율적 액션 조합</td><td style="padding:7px 10px;color:#64748b">navigate/click(링크)=페이지 변경→마지막 배치. input/scroll/extract=체이닝 가능.</td></tr>
        <tr style="border-bottom:1px solid #f1f5f9"><td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">&lt;reasoning_rules&gt;</td><td style="padding:7px 10px;color:#475569">추론 방식 강제</td><td style="padding:7px 10px;color:#64748b">thinking 블록에서: history 추적 → 이전 액션 성공/실패 판단(스크린샷 기준) → 다음 목표 결정. 명시적 추론 강제.</td></tr>
        <tr style="border-bottom:1px solid #f1f5f9"><td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">&lt;examples&gt;</td><td style="padding:7px 10px;color:#475569">출력 예시</td><td style="padding:7px 10px;color:#64748b">todo.md 작성 예시, evaluation/memory/next_goal 표현 예시. 직접 복붙 금지.</td></tr>
        <tr><td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">&lt;output&gt;</td><td style="padding:7px 10px;color:#475569">출력 형식 강제</td><td style="padding:7px 10px;color:#64748b">반드시 JSON. thinking / evaluation_previous_goal / memory / next_goal / current_plan_item / plan_update / action[] 구조. action은 절대 빈 배열 불가.</td></tr>
      </tbody>
    </table>

    <!-- Raw system prompt 접기 -->
    <div style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden">
      <div onclick="toggleSec('raw_sys')" style="cursor:pointer;display:flex;justify-content:space-between;align-items:center;padding:10px 14px;background:#f8fafc;user-select:none">
        <span style="font-size:11px;font-weight:700;color:#64748b">📄 Raw System Prompt 원문 보기</span>
        <svg id="arr_raw_sys" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2.5" style="transform:rotate(-90deg);transition:transform .2s"><polyline points="6 9 12 15 18 9"/></svg>
      </div>
      <div id="raw_sys" style="display:none;padding:14px">
        <pre class="mono">{esc(system_prompt_text)}</pre>
      </div>
    </div>

  </div>

  <!-- Raw LLM Output 설명 -->
  <div style="margin-top:16px;background:white;border:1px solid #e2e8f0;border-radius:10px;padding:16px">
    <div style="font-size:10px;font-weight:800;letter-spacing:.1em;color:#475569;margin-bottom:4px">📄 RAW LLM OUTPUT 구조</div>
    <div style="font-size:12px;color:#94a3b8;margin-bottom:12px">
      <code style="background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:11px">completion=AgentOutput(...) thinking=None redacted_thinking=None usage=ChatInvokeUsage(...) stop_reason='stop'</code>
    </div>

    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead>
        <tr style="background:#f8fafc">
          <th style="padding:7px 10px;text-align:left;border-bottom:2px solid #e2e8f0;color:#64748b;font-weight:700;white-space:nowrap">필드</th>
          <th style="padding:7px 10px;text-align:left;border-bottom:2px solid #e2e8f0;color:#64748b;font-weight:700">타입</th>
          <th style="padding:7px 10px;text-align:left;border-bottom:2px solid #e2e8f0;color:#64748b;font-weight:700">설명</th>
        </tr>
      </thead>
      <tbody>
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">completion</td>
          <td style="padding:7px 10px;color:#94a3b8;font-family:monospace;font-size:11px">AgentOutput</td>
          <td style="padding:7px 10px;color:#475569">LLM이 생성한 구조화 출력 전체. 아래 필드들을 모두 포함하는 Pydantic 객체. browser-use가 이걸 파싱해서 액션 실행.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9;background:#fafaf9">
          <td style="padding:7px 10px 7px 20px;font-family:monospace;color:#6366f1;white-space:nowrap">↳ thinking</td>
          <td style="padding:7px 10px;color:#94a3b8;font-family:monospace;font-size:11px">str | None</td>
          <td style="padding:7px 10px;color:#475569">LLM 내부 chain-of-thought. system prompt의 &lt;reasoning_rules&gt;에 따라 작성. 복잡한 스텝에서만 등장. <strong>다음 스텝 입력으로는 전달 안 됨</strong> (history엔 미포함).</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9;background:#fafaf9">
          <td style="padding:7px 10px 7px 20px;font-family:monospace;color:#6366f1;white-space:nowrap">↳ evaluation_previous_goal</td>
          <td style="padding:7px 10px;color:#94a3b8;font-family:monospace;font-size:11px">str</td>
          <td style="padding:7px 10px;color:#475569">직전 스텝 액션의 성공/실패 판단. 스크린샷(SoM 이미지)을 GROUND TRUTH로 사용. "Verdict: Success/Failure/Uncertain" 형태. 다음 스텝 history에 기록됨.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9;background:#fafaf9">
          <td style="padding:7px 10px 7px 20px;font-family:monospace;color:#6366f1;white-space:nowrap">↳ memory</td>
          <td style="padding:7px 10px;color:#94a3b8;font-family:monospace;font-size:11px">str</td>
          <td style="padding:7px 10px;color:#475569">이번 스텝에서 기억해 둘 핵심 정보 (1-3문장). 다음 스텝 agent_history의 Memory: 항목으로 삽입됨. LLM의 유일한 외부 메모리 수단.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9;background:#fafaf9">
          <td style="padding:7px 10px 7px 20px;font-family:monospace;color:#6366f1;white-space:nowrap">↳ next_goal</td>
          <td style="padding:7px 10px;color:#94a3b8;font-family:monospace;font-size:11px">str</td>
          <td style="padding:7px 10px;color:#475569">이번 스텝의 목표 한 문장. 사이드바에도 표시. 다음 스텝 history의 Next Goal: 항목으로 전달됨.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9;background:#fafaf9">
          <td style="padding:7px 10px 7px 20px;font-family:monospace;color:#6366f1;white-space:nowrap">↳ current_plan_item</td>
          <td style="padding:7px 10px;color:#94a3b8;font-family:monospace;font-size:11px">int (optional)</td>
          <td style="padding:7px 10px;color:#475569">현재 실행 중인 plan 항목 번호 (0-indexed). &lt;plan&gt; 태그에서 해당 항목에 [&gt;] 마커 표시. plan이 없으면 생략.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9;background:#fafaf9">
          <td style="padding:7px 10px 7px 20px;font-family:monospace;color:#6366f1;white-space:nowrap">↳ plan_update</td>
          <td style="padding:7px 10px;color:#94a3b8;font-family:monospace;font-size:11px">list[str] (optional)</td>
          <td style="padding:7px 10px;color:#475569">플랜 새로 작성 또는 수정 시만 등장. 다음 스텝부터 &lt;plan&gt;으로 INPUT에 삽입. 처음 등장하는 스텝(보통 S1)에서만 생성, 이후엔 장애물 만날 때 재작성.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9;background:#fafaf9">
          <td style="padding:7px 10px 7px 20px;font-family:monospace;color:#6366f1;white-space:nowrap">↳ action</td>
          <td style="padding:7px 10px;color:#94a3b8;font-family:monospace;font-size:11px">list[ActionModel]</td>
          <td style="padding:7px 10px;color:#475569">실행할 브라우저 액션 목록. 최대 3개. 페이지 변경 액션(navigate/click) 이후는 자동 스킵. browser-use가 순서대로 실행 후 결과를 다음 스텝 history에 기록.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">thinking</td>
          <td style="padding:7px 10px;color:#94a3b8;font-family:monospace;font-size:11px">None</td>
          <td style="padding:7px 10px;color:#475569">AgentOutput 바깥의 별도 thinking 필드. Anthropic extended thinking API용 슬롯. 현재 모델(Gemini)에서는 항상 None.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">redacted_thinking</td>
          <td style="padding:7px 10px;color:#94a3b8;font-family:monospace;font-size:11px">None</td>
          <td style="padding:7px 10px;color:#475569">Anthropic이 안전 이유로 가린 thinking 블록. 현재 항상 None.</td>
        </tr>
        <tr style="border-bottom:1px solid #f1f5f9">
          <td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">usage</td>
          <td style="padding:7px 10px;color:#94a3b8;font-family:monospace;font-size:11px">ChatInvokeUsage</td>
          <td style="padding:7px 10px;color:#475569">토큰 사용량. <code style="background:#f1f5f9;padding:1px 5px;border-radius:3px">prompt_tokens</code> (입력) / <code style="background:#f1f5f9;padding:1px 5px;border-radius:3px">prompt_cached_tokens</code> (캐시 히트) / <code style="background:#f1f5f9;padding:1px 5px;border-radius:3px">completion_tokens</code> (출력) / <code style="background:#f1f5f9;padding:1px 5px;border-radius:3px">total_tokens</code>.</td>
        </tr>
        <tr>
          <td style="padding:7px 10px;font-family:monospace;font-weight:700;color:#0f172a;white-space:nowrap">stop_reason</td>
          <td style="padding:7px 10px;color:#94a3b8;font-family:monospace;font-size:11px">str</td>
          <td style="padding:7px 10px;color:#475569">LLM 생성 종료 이유. <code style="background:#f1f5f9;padding:1px 5px;border-radius:3px">'stop'</code> = 정상 완료. <code style="background:#f1f5f9;padding:1px 5px;border-radius:3px">'length'</code> = max_tokens 초과 (출력 잘림). <code style="background:#f1f5f9;padding:1px 5px;border-radius:3px">'tool_use'</code> = 도구 호출.</td>
        </tr>
      </tbody>
    </table>
  </div>

</section>
"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"/>
<title>Agent I/O — {task_name}</title>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0 }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         background:#f1f5f9; color:#1e293b; display:flex; height:100vh; overflow:hidden }}

  /* 사이드바 */
  #sidebar {{ width:230px; min-width:230px; background:#0f172a; display:flex; flex-direction:column; overflow:hidden }}
  #sb-head {{ padding:16px 14px 12px; border-bottom:1px solid #1e293b }}
  #sb-head h2 {{ font-size:13px; font-weight:700; color:white; margin-bottom:2px }}
  #sb-head p  {{ font-size:11px; color:#64748b }}
  #sb-list {{ flex:1; overflow-y:auto; padding:6px 0 }}
  .sb-item {{ display:block; padding:9px 14px; text-decoration:none;
              border-left:3px solid transparent; transition:background .12s }}
  .sb-item:hover {{ background:#1e293b }}
  .sb-item.active {{ background:#1e293b; border-left-color:#6366f1 }}
  .sb-id   {{ display:block; font-size:12px; font-weight:700; font-family:monospace; color:#818cf8 }}
  .sb-goal {{ display:block; font-size:11px; color:#94a3b8; margin-top:2px; line-height:1.4 }}

  /* 메인 */
  #main {{ flex:1; overflow-y:auto; padding:28px 28px 60px }}

  /* 스텝 */
  .step-wrap {{ margin-bottom:40px; padding-bottom:40px; border-bottom:2px solid #e2e8f0 }}
  .step-wrap:last-child {{ border-bottom:none }}
  .step-title {{ display:flex; align-items:center; gap:12px; margin-bottom:18px }}
  .step-num  {{ background:#0f172a; color:white; padding:4px 13px; border-radius:6px;
               font-size:13px; font-weight:700; font-family:monospace }}
  .step-goal {{ font-size:14px; color:#475569; flex:1 }}

  /* I/O 플로우 */
  .io-flow {{ display:grid; grid-template-columns:1fr 44px 1fr; gap:0; align-items:start }}
  .io-col {{ display:flex; flex-direction:column; gap:8px }}
  .io-col-header {{ font-size:10px; font-weight:800; letter-spacing:.12em; text-transform:uppercase;
                    padding:6px 12px; border-radius:6px; margin-bottom:4px; text-align:center }}
  .in-header  {{ background:#1e40af; color:white }}
  .out-header {{ background:#166534; color:white }}

  /* 화살표 */
  .io-arrow {{ display:flex; flex-direction:column; align-items:center; justify-content:center;
               padding-top:36px; gap:6px }}
  .arrow-line  {{ width:2px; flex:1; background:#cbd5e1; min-height:30px }}
  .arrow-label {{ font-size:10px; font-weight:700; color:#94a3b8; letter-spacing:.08em;
                  background:#e2e8f0; padding:4px 6px; border-radius:4px; white-space:nowrap }}

  /* 섹션 카드 */
  .io-section {{ background:white; border:1px solid #e2e8f0; border-radius:10px; padding:14px 16px }}
  .io-sec-header {{ display:flex; align-items:center; justify-content:space-between }}

  /* 공통 */
  .label-sm {{ font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.07em;
               color:#94a3b8; margin-right:6px }}
  pre.mono {{ font-family:'JetBrains Mono',Menlo,monospace; font-size:12px; line-height:1.6;
              color:#334155; white-space:pre-wrap; word-break:break-word; background:#f8fafc;
              border-radius:6px; padding:10px 12px; border:1px solid #f1f5f9 }}

  /* 스크롤바 */
  #sb-list::-webkit-scrollbar {{ width:4px }}
  #sb-list::-webkit-scrollbar-thumb {{ background:#334155; border-radius:2px }}
  #main::-webkit-scrollbar {{ width:6px }}
  #main::-webkit-scrollbar-thumb {{ background:#cbd5e1; border-radius:3px }}
</style>
</head>
<body>

<div id="sidebar">
  <div id="sb-head">
    <h2>{task_name}</h2>
    <p>{len(steps)} steps</p>
  </div>
  <div id="sb-list">
    <a class="sb-item" href="#legend" onclick="setActive(this)">
      <span class="sb-id" style="color:#94a3b8">?</span>
      <span class="sb-goal">시스템 구조 & 필드 설명</span>
    </a>
    {sidebar_items}
  </div>
</div>

<div id="main">{legend_html}{sections_html}</div>

<script>
function toggleSec(id) {{
  const el = document.getElementById(id);
  const arr = document.getElementById('arr_' + id);
  if (el.style.display === 'none') {{
    el.style.display = '';
    if (arr) arr.style.transform = '';
  }} else {{
    el.style.display = 'none';
    if (arr) arr.style.transform = 'rotate(-90deg)';
  }}
}}
function setActive(el) {{
  document.querySelectorAll('.sb-item').forEach(a => a.classList.remove('active'));
  el.classList.add('active');
}}
// 스크롤 연동
const main = document.getElementById('main');
const secs = [...document.querySelectorAll('.step-wrap')];
main.addEventListener('scroll', () => {{
  let cur = secs[0];
  secs.forEach(s => {{ if (s.offsetTop - main.scrollTop < 140) cur = s; }});
  const sid = cur.id;
  document.querySelectorAll('.sb-item').forEach(a => {{
    a.classList.toggle('active', a.getAttribute('href') === '#' + sid);
  }});
}});
document.querySelector('.sb-item')?.classList.add('active');
</script>
</body>
</html>
"""


# ── 진입점 ────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("사용법: python viz_io.py <task_폴더>")
        sys.exit(1)

    task_dir = Path(sys.argv[1])
    if not task_dir.is_dir():
        print(f"❌ 폴더 없음: {task_dir}")
        sys.exit(1)

    step_dirs = sorted(
        [d for d in task_dir.iterdir() if d.is_dir() and d.name.startswith("S") and d.name[1:].isdigit()],
        key=lambda d: int(d.name[1:]),
    )
    if not step_dirs:
        print(f"❌ 스텝 폴더(S1/, S2/ ...) 없음: {task_dir}")
        sys.exit(1)

    print(f"📂 {task_dir.name}  ({len(step_dirs)} steps)")

    # system prompt는 S1에서 한 번만 읽기
    sys_path = step_dirs[0] / "system_prompt.txt"
    system_prompt_text = sys_path.read_text(encoding="utf-8") if sys_path.exists() else ""

    # S0 — 자동 초기화 스텝 (S1 데이터에서 추출)
    s1_up = step_dirs[0] / "user_prompt.txt"
    s1_prompt = parse_user_prompt(s1_up.read_text(encoding="utf-8")) if s1_up.exists() else {}
    s0_html = build_step_s0(
        task_text=s1_prompt.get("user_request", ""),
        history_text=s1_prompt.get("history", ""),
    )
    steps = [{"num": "0", "goal": "자동 초기화 (URL 추출 → navigate)", "action": "navigate", "html": s0_html}]

    for sd in step_dirs:
        n = int(sd.name[1:])

        up = sd / "user_prompt.txt"
        prompt = parse_user_prompt(up.read_text(encoding="utf-8")) if up.exists() else {}

        meta = parse_metadata(sd / "metadata.json")
        llm  = parse_llm_output(sd / "llm_output.json")

        img_b64 = None
        for name in ["som_image.png", "som_debug.png", "screenshot.png"]:
            p = sd / name
            if p.exists():
                img_b64 = base64.b64encode(p.read_bytes()).decode()
                break

        html = build_step(n, prompt, meta, llm, img_b64, system_prompt_text)
        steps.append({
            "num":    n,
            "goal":   meta.get("next_goal",""),
            "action": meta.get("action",""),
            "html":   html,
        })
        print(f"  ✅ S{n}  goal={meta.get('next_goal','')[:50]}")

    out = task_dir / "viz_io.html"
    out.write_text(build_html(task_dir, steps, system_prompt_text), encoding="utf-8")
    print(f"\n✅ {out}")
    print(f"   open '{out}'")


if __name__ == "__main__":
    main()
