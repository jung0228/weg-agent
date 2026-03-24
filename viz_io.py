"""
viz_io.py — Web Agent I/O Visualizer
user_prompt.txt + screenshot PNG → 깔끔한 HTML 뷰어 생성

사용법:
  python viz_io.py <user_prompt.txt 경로> [--screenshot <png 경로>] [--action <action.txt 경로>]

예시:
  python viz_io.py output/20260115_094348/debug/A1/S5/user_prompt.txt \
                   --screenshot output/20260115_094348/debug/A1/S5/screenshot.png \
                   --action output/20260115_094348/debug/A1/S5/action.txt
"""

import argparse
import base64
import re
import sys
from pathlib import Path

# ── 파서 ────────────────────────────────────────────────────────────────────

def parse_user_prompt(text: str) -> dict:
    """user_prompt.txt 파싱 → 구조화된 dict 반환"""
    result = {
        "instruction": "",
        "history": [],
        "elements": [],
        "raw": text,
    }

    # 지시문
    m = re.search(r"The instruction is to (.+?)(?:\n|History)", text, re.DOTALL)
    if m:
        result["instruction"] = m.group(1).strip()

    # 히스토리
    m = re.search(r"History actions:\s*\[([^\]]*)\]", text, re.DOTALL)
    if m:
        raw_hist = m.group(1).strip()
        if raw_hist:
            result["history"] = [h.strip() for h in raw_hist.split(",") if h.strip()]

    # 요소 목록: [index] [TYPE] [text_or_empty]
    element_pattern = re.compile(r"\[(\d+)\]\s+\[([A-Z]+)\]\s+\[([^\]]*)\]")
    for match in element_pattern.finditer(text):
        idx, etype, content = match.group(1), match.group(2), match.group(3)
        result["elements"].append({
            "index": int(idx),
            "type": etype,
            "content": content,
        })

    # 인덱스 순 정렬
    result["elements"].sort(key=lambda x: x["index"])
    return result


# ── HTML 생성 ────────────────────────────────────────────────────────────────

TYPE_COLOR = {
    "A":      ("#dbeafe", "#1d4ed8"),   # 파랑 — 링크
    "BUTTON": ("#dcfce7", "#15803d"),   # 초록 — 버튼
    "INPUT":  ("#fef9c3", "#92400e"),   # 노랑 — 입력창
    "SELECT": ("#ede9fe", "#6d28d9"),   # 보라 — 드롭다운
    "DIV":    ("#f1f5f9", "#475569"),   # 회색 — 컨테이너
}

def elem_badge(etype: str) -> str:
    bg, fg = TYPE_COLOR.get(etype, ("#f1f5f9", "#334155"))
    return (f'<span style="background:{bg};color:{fg};'
            f'padding:2px 7px;border-radius:4px;font-size:11px;'
            f'font-weight:600;font-family:monospace">{etype}</span>')


def build_html(data: dict, screenshot_b64: str | None, action_text: str | None, step_label: str) -> str:
    instruction_html = data["instruction"] or "<em style='color:#9ca3af'>없음</em>"

    # 히스토리 칩
    if data["history"]:
        hist_chips = "".join(
            f'<span style="background:#f3f4f6;border:1px solid #e5e7eb;'
            f'border-radius:4px;padding:3px 8px;font-size:12px;margin:2px;'
            f'display:inline-block">{h}</span>'
            for h in data["history"]
        )
        hist_html = f'<div style="display:flex;flex-wrap:wrap;gap:4px">{hist_chips}</div>'
    else:
        hist_html = '<span style="color:#9ca3af;font-size:13px">없음 (첫 번째 스텝)</span>'

    # 요소 테이블
    rows = ""
    for el in data["elements"]:
        content_disp = el["content"] if el["content"] else '<span style="color:#9ca3af">—</span>'
        rows += (
            f'<tr style="border-bottom:1px solid #f1f5f9">'
            f'<td style="padding:6px 10px;text-align:center;font-family:monospace;'
            f'font-weight:700;color:#1e293b">[{el["index"]}]</td>'
            f'<td style="padding:6px 10px">{elem_badge(el["type"])}</td>'
            f'<td style="padding:6px 10px;font-size:13px;color:#334155;max-width:260px;'
            f'word-break:break-word">{content_disp}</td>'
            f'</tr>'
        )

    # 스크린샷
    if screenshot_b64:
        screenshot_html = (
            f'<img src="data:image/png;base64,{screenshot_b64}" '
            f'style="width:100%;border-radius:8px;border:1px solid #e5e7eb" />'
        )
    else:
        screenshot_html = (
            '<div style="width:100%;aspect-ratio:16/9;background:#f8fafc;'
            'border:2px dashed #cbd5e1;border-radius:8px;display:flex;'
            'align-items:center;justify-content:center;color:#94a3b8;font-size:14px">'
            'screenshot 없음</div>'
        )

    # 액션 출력
    if action_text:
        action_html = (
            f'<pre style="margin:0;white-space:pre-wrap;font-family:monospace;'
            f'font-size:13px;color:#1e293b">{action_text.strip()}</pre>'
        )
        action_color = "#dcfce7"
        action_border = "#86efac"
    else:
        action_html = '<span style="color:#9ca3af;font-size:13px">action.txt 없음</span>'
        action_color = "#f8fafc"
        action_border = "#e2e8f0"

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<title>Agent I/O — {step_label}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f8fafc; color: #1e293b; padding: 24px; }}
  .card {{ background: white; border-radius: 12px; border: 1px solid #e2e8f0;
           padding: 20px; margin-bottom: 16px; }}
  .label {{ font-size: 11px; font-weight: 700; text-transform: uppercase;
            letter-spacing: .08em; color: #94a3b8; margin-bottom: 8px; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ background: #f8fafc; font-size: 11px; font-weight: 700;
        text-transform: uppercase; letter-spacing:.06em; color:#64748b;
        padding: 8px 10px; text-align:left; border-bottom:2px solid #e2e8f0; }}
  tr:hover {{ background: #f8fafc; }}
  h1 {{ font-size: 20px; font-weight: 700; margin-bottom: 4px; }}
  .badge-step {{ background:#0f172a;color:white;padding:3px 10px;
                 border-radius:6px;font-size:12px;font-family:monospace; }}
</style>
</head>
<body>

<!-- 헤더 -->
<div style="display:flex;align-items:center;gap:12px;margin-bottom:20px">
  <h1>Agent I/O Viewer</h1>
  <span class="badge-step">{step_label}</span>
</div>

<!-- 태스크 지시문 -->
<div class="card">
  <div class="label">📋 Task Instruction</div>
  <p style="font-size:15px;line-height:1.6;color:#1e293b">{instruction_html}</p>
</div>

<!-- 히스토리 -->
<div class="card">
  <div class="label">🕓 History Actions (이전까지 수행한 액션)</div>
  {hist_html}
</div>

<!-- 스크린샷 + 요소 테이블 -->
<div class="grid">
  <!-- 왼쪽: SoM 스크린샷 -->
  <div class="card">
    <div class="label">🖼 SoM Screenshot (Set-of-Mark)</div>
    {screenshot_html}
    <p style="font-size:11px;color:#94a3b8;margin-top:8px">
      화면의 클릭 가능한 요소에 번호([0]~[N])가 붙어있음
    </p>
  </div>

  <!-- 오른쪽: 요소 목록 -->
  <div class="card">
    <div class="label">📡 Screen Elements ({len(data["elements"])}개 인터랙티브 요소)</div>
    <div style="overflow-y:auto;max-height:480px">
      <table>
        <thead>
          <tr>
            <th>Index</th>
            <th>Type</th>
            <th>Content</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </div>
    <div style="margin-top:12px;display:flex;flex-wrap:wrap;gap:6px">
      {"".join(f'{elem_badge(t)} <span style="font-size:11px;color:#64748b">{label}</span>&nbsp;&nbsp;' for t, label in [("A","링크"),("BUTTON","버튼"),("INPUT","입력창"),("SELECT","드롭다운"),("DIV","컨테이너")])}
    </div>
  </div>
</div>

<!-- 에이전트 출력 액션 -->
<div class="card" style="background:{action_color};border-color:{action_border}">
  <div class="label">🤖 Agent Output Action</div>
  {action_html}
</div>

</body>
</html>
"""


# ── 진입점 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Web Agent I/O Visualizer")
    parser.add_argument("prompt", help="user_prompt.txt 경로")
    parser.add_argument("--screenshot", help="SoM PNG 경로")
    parser.add_argument("--action", help="action.txt 경로 (에이전트 출력)")
    parser.add_argument("--output", help="저장할 HTML 경로 (기본: 같은 폴더)")
    args = parser.parse_args()

    prompt_path = Path(args.prompt)
    if not prompt_path.exists():
        print(f"❌ 파일 없음: {prompt_path}")
        sys.exit(1)

    text = prompt_path.read_text(encoding="utf-8")
    data = parse_user_prompt(text)

    # 스크린샷 자동 탐색 (같은 폴더에 screenshot.png / som.png 등)
    screenshot_b64 = None
    screenshot_path = Path(args.screenshot) if args.screenshot else None
    if screenshot_path is None:
        for name in ["screenshot.png", "som.png", "screen.png", "image.png"]:
            candidate = prompt_path.parent / name
            if candidate.exists():
                screenshot_path = candidate
                break
    if screenshot_path and screenshot_path.exists():
        screenshot_b64 = base64.b64encode(screenshot_path.read_bytes()).decode()
        print(f"✅ 스크린샷: {screenshot_path}")

    # 액션 자동 탐색
    action_text = None
    action_path = Path(args.action) if args.action else None
    if action_path is None:
        for name in ["action.txt", "output.txt", "response.txt"]:
            candidate = prompt_path.parent / name
            if candidate.exists():
                action_path = candidate
                break
    if action_path and action_path.exists():
        action_text = action_path.read_text(encoding="utf-8")
        print(f"✅ 액션: {action_path}")

    # 스텝 라벨 (경로에서 추출)
    parts = prompt_path.parts
    step_label = "/".join(parts[-4:]) if len(parts) >= 4 else str(prompt_path)

    html = build_html(data, screenshot_b64, action_text, step_label)

    out_path = Path(args.output) if args.output else prompt_path.parent / "io_viewer.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"✅ 저장됨: {out_path}")
    print(f"   → 브라우저로 열기: open '{out_path}'")


if __name__ == "__main__":
    main()
