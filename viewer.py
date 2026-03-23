"""
viewer.py — weg-agent 실행 결과 뷰어
eval_results 폴더를 읽어서 HTML 뷰어 생성

사용법:
  python viewer.py                                          # 최근 run 자동 선택
  python viewer.py eval_results/korail_dry_20260320_133841 # run 폴더 지정
  python viewer.py --all                                    # 전체 run 인덱스 생성
"""

import argparse
import base64
import json
import sys
from pathlib import Path

EVAL_DIR = Path("eval_results")


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def screenshot_list(task_dir: Path) -> list[Path]:
    # S1/, S2/, ... 구조 우선
    step_dirs = sorted(
        [d for d in task_dir.iterdir() if d.is_dir() and d.name.startswith("S") and d.name[1:].isdigit()],
        key=lambda d: int(d.name[1:]),
    )
    if step_dirs:
        shots = []
        for sd in step_dirs:
            img = sd / "som_image.png"
            if img.exists():
                shots.append(img)
        if shots:
            return shots
    # fallback: 기존 screenshot{n}.png
    return sorted(
        task_dir.glob("screenshot*.png"),
        key=lambda p: int("".join(filter(str.isdigit, p.stem)) or "0"),
    )


def step_metadata(task_dir: Path) -> list[dict]:
    """S1/, S2/, ... 폴더에서 metadata.json 목록 반환"""
    step_dirs = sorted(
        [d for d in task_dir.iterdir() if d.is_dir() and d.name.startswith("S") and d.name[1:].isdigit()],
        key=lambda d: int(d.name[1:]),
    )
    metas = []
    for sd in step_dirs:
        mp = sd / "metadata.json"
        if mp.exists():
            metas.append(json.loads(mp.read_text()))
        else:
            metas.append({})
    return metas


def build_task_html(task_dir: Path, result: dict) -> str:
    shots = screenshot_list(task_dir)
    metas = step_metadata(task_dir)

    # 스텝별 상세 정보 패널 (JSON)
    step_panels = ""
    for i, meta in enumerate(metas):
        sd = task_dir / f"S{i+1}"
        acc = (sd / "acc_tree.txt").read_text(encoding="utf-8") if (sd / "acc_tree.txt").exists() else ""
        user_p = (sd / "user_prompt.txt").read_text(encoding="utf-8") if (sd / "user_prompt.txt").exists() else ""
        # acc_tree 요소 수
        elem_count = len([l for l in acc.splitlines() if l.strip().startswith("[")])
        action_raw = meta.get("action", "").replace("<", "&lt;").replace(">", "&gt;")
        memory_raw = (meta.get("memory", "") or "").replace("<", "&lt;")
        goal_raw = (meta.get("next_goal", "") or "").replace("<", "&lt;")
        eval_raw = (meta.get("evaluation_previous_goal", "") or "").replace("<", "&lt;")
        acc_html = acc.replace("<", "&lt;").replace(">", "&gt;")

        step_panels += f"""
        <div class="step-panel" id="panel-{i}" style="display:{'block' if i==0 else 'none'}">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px">
            <div>
              <div class="label">🎯 Eval / Memory / Goal</div>
              <div style="font-size:12px;line-height:1.7;background:#f8fafc;border-radius:6px;padding:10px">
                <b style="color:#64748b">Eval:</b> {eval_raw or '—'}<br>
                <b style="color:#64748b">Memory:</b> {memory_raw or '—'}<br>
                <b style="color:#64748b">Goal:</b> {goal_raw or '—'}
              </div>
              <div class="label" style="margin-top:10px">🤖 Action</div>
              <pre style="font-size:11px;background:#0f172a;color:#7dd3fc;border-radius:6px;
                          padding:10px;overflow-x:auto;white-space:pre-wrap">{action_raw or '—'}</pre>
            </div>
            <div>
              <div class="label">📡 Acc Tree ({elem_count}개 요소)</div>
              <pre style="font-size:11px;background:#f8fafc;border:1px solid #e2e8f0;
                          border-radius:6px;padding:10px;overflow-y:auto;max-height:220px;
                          white-space:pre-wrap">{acc_html or '—'}</pre>
            </div>
          </div>
        </div>"""

    # 스크린샷 슬라이더 아이템
    slide_items = ""
    thumb_items = ""
    for i, shot in enumerate(shots):
        active = "active" if i == 0 else ""
        img_b64 = b64(shot)
        slide_items += f"""
        <div class="slide {active}" id="slide-{i}">
          <img src="data:image/png;base64,{img_b64}"
               style="width:100%;border-radius:8px;display:block" />
          <div class="step-label">Step {i+1} / {len(shots)}</div>
        </div>"""
        thumb_items += f"""
        <img src="data:image/png;base64,{img_b64}"
             class="thumb {active}" onclick="goTo({i})"
             title="Step {i+1}" />"""

    # 결과 박스
    success = result.get("is_done", False)
    verdict = result.get("judge_verdict", None)
    color = "#dcfce7" if success else "#fef2f2"
    border = "#86efac" if success else "#fca5a5"
    icon = "✅" if success else "❌"

    verdict_html = ""
    if verdict is not None:
        vcolor = "#dcfce7" if verdict else "#fef2f2"
        vborder = "#86efac" if verdict else "#fca5a5"
        verdict_html = f"""
        <div style="margin-top:12px;padding:10px 14px;background:{vcolor};
                    border:1px solid {vborder};border-radius:8px">
          <span style="font-size:12px;font-weight:700;color:#64748b">JUDGE 판정</span><br>
          <span style="font-size:15px;font-weight:700">
            {"✅ SUCCESS" if verdict else "❌ NOT SUCCESS"}
          </span>
        </div>"""

    elapsed = result.get("elapsed_sec", 0)
    final_answer = result.get("final_answer", "").replace("\n", "<br>")

    return f"""
    <div class="card">
      <div class="label">📋 Task</div>
      <p style="font-size:15px;line-height:1.7">{result.get("ques","")}</p>
      <a href="{result.get("web","")}" target="_blank"
         style="font-size:12px;color:#3b82f6">{result.get("web","")}</a>
    </div>

    <div style="display:grid;grid-template-columns:1fr 360px;gap:16px">

      <!-- 스크린샷 슬라이더 -->
      <div class="card">
        <div class="label">🖼 스텝별 스크린샷 ({len(shots)}장)</div>
        <div class="slider-wrap">
          <div class="slides">{"빈 화면" if not slide_items else slide_items}</div>
          <button class="nav-btn left" onclick="move(-1)">‹</button>
          <button class="nav-btn right" onclick="move(1)">›</button>
        </div>
        <div class="thumbs">{thumb_items}</div>
        {step_panels}
      </div>

      <!-- 결과 -->
      <div>
        <div class="card" style="background:{color};border-color:{border}">
          <div class="label">🤖 Final Answer</div>
          <div style="font-size:13px;font-weight:700;margin-bottom:8px">
            {icon} {"완료" if success else "미완료"} &nbsp;
            <span style="font-weight:400;color:#64748b">{elapsed:.1f}초</span>
          </div>
          <p style="font-size:14px;line-height:1.7;color:#1e293b">{final_answer or "—"}</p>
          {verdict_html}
        </div>

        <div class="card" style="margin-top:0">
          <div class="label">📊 메타데이터</div>
          <table style="width:100%;font-size:13px">
            <tr><td style="color:#64748b;padding:3px 0">Task ID</td>
                <td style="font-family:monospace">{result.get("task_id","")}</td></tr>
            <tr><td style="color:#64748b;padding:3px 0">스텝 수</td>
                <td>{len(shots)}장</td></tr>
            <tr><td style="color:#64748b;padding:3px 0">소요 시간</td>
                <td>{elapsed:.1f}초</td></tr>
            <tr><td style="color:#64748b;padding:3px 0">Dry Run</td>
                <td>{"예" if result.get("dry_run") else "아니오"}</td></tr>
          </table>
        </div>
      </div>
    </div>

    <script>
    let cur = 0;
    const slides = document.querySelectorAll('.slide');
    const thumbs = document.querySelectorAll('.thumb');
    function goTo(n) {{
      slides[cur].classList.remove('active');
      thumbs[cur].classList.remove('active');
      const prevPanel = document.getElementById('panel-' + cur);
      if (prevPanel) prevPanel.style.display = 'none';
      cur = (n + slides.length) % slides.length;
      slides[cur].classList.add('active');
      thumbs[cur].classList.add('active');
      thumbs[cur].scrollIntoView({{block:'nearest',inline:'center'}});
      const nextPanel = document.getElementById('panel-' + cur);
      if (nextPanel) nextPanel.style.display = 'block';
    }}
    function move(d) {{ goTo(cur + d); }}
    document.addEventListener('keydown', e => {{
      if (e.key === 'ArrowRight') move(1);
      if (e.key === 'ArrowLeft')  move(-1);
    }});
    </script>
    """


CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f8fafc; color: #1e293b; padding: 24px; }
.card { background: white; border-radius: 12px; border: 1px solid #e2e8f0;
        padding: 20px; margin-bottom: 16px; }
.label { font-size: 11px; font-weight: 700; text-transform: uppercase;
         letter-spacing: .08em; color: #94a3b8; margin-bottom: 10px; }

/* 슬라이더 */
.slider-wrap { position: relative; }
.slides { position: relative; }
.slide { display: none; }
.slide.active { display: block; }
.step-label { text-align:center; font-size:12px; color:#64748b; margin-top:6px; }
.nav-btn { position:absolute; top:50%; transform:translateY(-50%);
           background:rgba(0,0,0,.45); color:white; border:none;
           border-radius:50%; width:36px; height:36px; font-size:20px;
           cursor:pointer; display:flex; align-items:center; justify-content:center; }
.nav-btn.left  { left: 6px; }
.nav-btn.right { right: 6px; }
.nav-btn:hover { background:rgba(0,0,0,.7); }

/* 썸네일 */
.thumbs { display:flex; gap:6px; overflow-x:auto; padding:10px 0 4px;
          scrollbar-width:thin; }
.thumb { height:52px; border-radius:4px; border:2px solid transparent;
         cursor:pointer; flex-shrink:0; object-fit:cover; opacity:.6;
         transition:.15s; }
.thumb.active { border-color:#3b82f6; opacity:1; }
.thumb:hover  { opacity:1; }

/* 헤더 */
h1 { font-size:22px; font-weight:700; }
.run-badge { background:#0f172a; color:white; padding:3px 10px;
             border-radius:6px; font-size:12px; font-family:monospace; }
"""


def build_run_html(run_dir: Path) -> str:
    """run 폴더 전체 → HTML (task 탭 형식)"""
    task_dirs = sorted([d for d in run_dir.iterdir() if d.is_dir()])
    if not task_dirs:
        return "<p>태스크 없음</p>"

    # 탭 헤더
    tab_btns = ""
    tab_contents = ""
    for i, td in enumerate(task_dirs):
        result_path = td / "result.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else {}
        task_id = result.get("task_id", td.name)
        is_done = result.get("is_done", False)
        icon = "✅" if is_done else "❌"
        active = "active" if i == 0 else ""

        tab_btns += f"""
        <button class="tab-btn {active}" onclick="showTab({i})">
          {icon} {task_id}
        </button>"""

        content = build_task_html(td, result)
        tab_contents += f"""
        <div class="tab-panel {active}" id="tab-{i}">
          {content}
        </div>"""

    # 요약 통계
    results = []
    for td in task_dirs:
        rp = td / "result.json"
        if rp.exists():
            results.append(json.loads(rp.read_text()))
    total = len(results)
    done = sum(1 for r in results if r.get("is_done"))
    avg_sec = sum(r.get("elapsed_sec", 0) for r in results) / max(total, 1)

    summary = f"""
    <div class="card" style="display:flex;gap:32px;align-items:center;margin-bottom:16px">
      <div><span style="font-size:28px;font-weight:700">{done}/{total}</span>
           <span style="font-size:13px;color:#64748b;margin-left:6px">완료</span></div>
      <div><span style="font-size:28px;font-weight:700">{done/max(total,1)*100:.0f}%</span>
           <span style="font-size:13px;color:#64748b;margin-left:6px">성공률</span></div>
      <div><span style="font-size:28px;font-weight:700">{avg_sec:.0f}s</span>
           <span style="font-size:13px;color:#64748b;margin-left:6px">평균 소요</span></div>
    </div>"""

    return f"""
    {summary}
    <div class="tabs">{tab_btns}</div>
    {tab_contents}
    <script>
    function showTab(n) {{
      document.querySelectorAll('.tab-btn').forEach((b,i)=>
        b.classList.toggle('active', i===n));
      document.querySelectorAll('.tab-panel').forEach((p,i)=>
        p.classList.toggle('active', i===n));
    }}
    </script>
    """


def wrap_html(body: str, title: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<title>{title}</title>
<style>
{CSS}
.tabs {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }}
.tab-btn {{ padding:7px 14px; border-radius:8px; border:1px solid #e2e8f0;
            background:white; cursor:pointer; font-size:13px; }}
.tab-btn.active {{ background:#0f172a; color:white; border-color:#0f172a; }}
.tab-panel {{ display:none; }}
.tab-panel.active {{ display:block; }}
</style>
</head>
<body>
<div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">
  <h1>weg-agent I/O Viewer</h1>
  <span class="run-badge">{title}</span>
</div>
{body}
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", nargs="?", help="eval_results/<run> 폴더")
    parser.add_argument("--all", action="store_true", help="전체 run HTML 생성")
    args = parser.parse_args()

    if args.all:
        for run_dir in sorted(EVAL_DIR.iterdir()):
            if run_dir.is_dir() and not run_dir.name.startswith("."):
                out = run_dir / "viewer.html"
                html = wrap_html(build_run_html(run_dir), run_dir.name)
                out.write_text(html, encoding="utf-8")
                print(f"✅ {out}")
        return

    # 단일 run
    if args.run_dir:
        run_dir = Path(args.run_dir)
    else:
        # 최근 run 자동 선택
        runs = sorted(
            [d for d in EVAL_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if not runs:
            print("❌ eval_results 폴더에 run이 없어요")
            sys.exit(1)
        run_dir = runs[0]
        print(f"📂 최근 run 선택: {run_dir.name}")

    out = run_dir / "viewer.html"
    html = wrap_html(build_run_html(run_dir), run_dir.name)
    out.write_text(html, encoding="utf-8")
    print(f"✅ 저장: {out}")
    import subprocess
    subprocess.run(["open", str(out)])


if __name__ == "__main__":
    main()
