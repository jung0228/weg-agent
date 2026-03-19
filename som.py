"""
som.py — 하이브리드 비전 + SOM(Set-of-Marks) 화면 인식

SOM_MODE=1 환경변수 설정 시:
  DOM에서 인터랙티브 요소를 추출해 스크린샷에 번호 오버레이를 그린다.
  LLM은 스크린샷의 번호 배지와 함께 제공되는 요소 목록을 참고해 좌표를 결정한다.

SOM_MODE=0 (기본):
  순수 비전 모드 — 오버레이 없이 원본 스크린샷만 사용한다.
"""
import base64
import io
import os
from dataclasses import dataclass, field

from playwright.async_api import Page

# ── 환경변수 ───────────────────────────────────────────────────────
_DEBUG_DIR = os.environ.get("SOM_DEBUG_DIR", "")
_SOM_MODE  = os.environ.get("SOM_MODE", "0").strip() == "1"
_debug_counter = 0


# ── JS: 인터랙티브 요소 BBox 추출 (다나와 견적 특화) ─────────────
_JS_GET_INTERACTIVE = """
() => {
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    // ── 1. ARIA/시맨틱 role 계산 ─────────────────────────────────
    // class 이름 대신 WAI-ARIA 표준 role 기반 — 어느 사이트에서도 동작
    function getRole(el) {
        const tag  = el.tagName.toLowerCase();
        const type = (el.getAttribute('type') || '').toLowerCase();

        // 명시적 ARIA role 우선
        const aria = el.getAttribute('role');
        if (aria && aria !== 'none' && aria !== 'presentation') return aria;

        // HTML 시맨틱 태그 → 암묵적 role (WAI-ARIA 1.2 매핑)
        if (tag === 'button' || type === 'button' || type === 'submit' || type === 'reset')
            return 'button';
        if (tag === 'a' && el.hasAttribute('href'))
            return 'link';
        if (type === 'checkbox')
            return 'checkbox';
        if (type === 'radio')
            return 'radio';
        if (tag === 'select')
            return 'combobox';
        if (type === 'text' || type === 'search' || type === 'email' ||
            type === 'url'  || type === 'number' || tag === 'textarea')
            return 'textbox';

        // label → 연결된 control의 role 상속
        // 예: <label class="item_checkbox"> → <input type="checkbox"> → 'checkbox'
        // 이 방식으로 class명 없이도 다나와 필터 레이블을 정확히 잡을 수 있음
        if (tag === 'label') {
            const ctrl = el.control ||
                         document.getElementById(el.getAttribute('for') || '');
            if (ctrl) {
                const ctype = (ctrl.getAttribute('type') || '').toLowerCase();
                if (ctype === 'checkbox') return 'checkbox';
                if (ctype === 'radio')    return 'radio';
                return 'textbox';
            }
        }

        // onclick / tabIndex 있으면 button으로 취급
        if (el.hasAttribute('onclick') || el.getAttribute('tabindex') === '0')
            return 'button';

        return null;  // 인터랙티브하지 않음
    }

    // ── 2. 제외할 조상 영역 (nav/배너/광고 — 사이트별 블랙리스트) ─
    // 이 부분만 사이트 특화. role 기반 탐지는 범용.
    const BLOCK_ANCESTOR = [
        '.main-header', '.main-header__wrap',
        '.main-header__search', '.search__box',
        '.main_visual', '.visual_area',
        '.swiper-wrapper', '.swiper-slide', '.slide_wrap',
        '.banner_area', '.banner_box', '.smart_banner',
        '.text_img_view .smart_banner', '[class*="visual"]',
        '.main-wing__fixed', '.main-wing',
        '.estimate_ad', '.estimate_widget',
        '.ad_area', '[id*="Banner"]',
        '.util_area',
    ];

    function isBlocked(el) {
        for (const sel of BLOCK_ANCESTOR) {
            try { if (el.closest(sel)) return true; } catch(e) {}
        }
        return false;
    }

    // ── 3. 가시성 체크 ────────────────────────────────────────────
    function isVisible(el, rect) {
        if (rect.width < 6 || rect.height < 6) return false;
        if (rect.bottom < 0 || rect.top > vh) return false;
        if (rect.right < 0 || rect.left > vw) return false;
        const st = window.getComputedStyle(el);
        if (st.display === 'none' || st.visibility === 'hidden') return false;
        if (parseFloat(st.opacity) < 0.05) return false;
        return true;
    }

    // ── 4. 접근 가능한 이름(Accessible Name) 계산 ────────────────
    // aria-label > aria-labelledby > innerText > value > title > placeholder
    function getAccessibleName(el) {
        const ariaLabel = el.getAttribute('aria-label');
        if (ariaLabel) return ariaLabel.trim().slice(0, 40);

        const labelledBy = el.getAttribute('aria-labelledby');
        if (labelledBy) {
            const ref = document.getElementById(labelledBy);
            if (ref) return (ref.innerText || '').trim().slice(0, 40);
        }

        return (
            el.innerText     ||
            el.value         ||
            el.getAttribute('title')       ||
            el.getAttribute('placeholder') || ''
        ).trim().replace(/\\s+/g, ' ').slice(0, 40);
    }

    // ── 5. 전체 DOM 순회 — role 기반 수집 ────────────────────────
    const results = [];
    const seen    = new Set();
    let idx = 1;
    const MAX = 50;

    // role → kind 매핑
    const ROLE_KIND = {
        button:   'button',
        link:     'link',
        checkbox: 'checkbox',
        radio:    'checkbox',
        textbox:  'input',
        combobox: 'select',
        searchbox:'input',
        menuitem: 'button',
        option:   'button',
    };

    // 후보 요소: 흔한 인터랙티브 태그만 먼저 훑어서 성능 확보
    const CANDIDATE_SEL = 'a,button,input,select,textarea,label,[role],[onclick],[tabindex="0"]';
    const candidates = document.querySelectorAll(CANDIDATE_SEL);

    for (const el of candidates) {
        if (seen.has(el)) continue;
        seen.add(el);

        const role = getRole(el);
        if (!role) continue;

        const kind = ROLE_KIND[role];
        if (!kind) continue;

        // hidden input(checkbox)은 시각적으로 없음 → 연결된 label이 대신 잡힘
        if (el.tagName.toLowerCase() === 'input' && el.type === 'checkbox') continue;

        if (isBlocked(el)) continue;

        const rect = el.getBoundingClientRect();
        if (!isVisible(el, rect)) continue;

        // 배너/광고성 대형 요소 제외
        if (rect.width > 500 || rect.height > 120) continue;

        const name = getAccessibleName(el);
        if (!name) continue;  // 이름 없는 요소 스킵

        const cx = Math.round(rect.left + rect.width  / 2);
        const cy = Math.round(rect.top  + rect.height / 2);

        results.push({
            id:     idx++,
            kind,
            text:   name,
            role,
            x:      cx,
            y:      cy,
            left:   Math.round(rect.left),
            top:    Math.round(rect.top),
            right:  Math.round(rect.right),
            bottom: Math.round(rect.bottom),
        });

        if (idx > MAX) break;
    }
    return results;
}
"""


# ── ScreenState ────────────────────────────────────────────────────

@dataclass
class ScreenState:
    screenshot_b64: str        # base64 PNG (SOM_MODE=1이면 오버레이 포함)
    page_title: str
    page_url: str
    width: int                 # 뷰포트 픽셀 너비
    height: int                # 뷰포트 픽셀 높이
    element_map: str = ""      # SOM 요소 목록 텍스트 (SOM_MODE=0이면 빈 문자열)
    # id → {x, y, kind, text} 매핑 — executor에서 Click [N] 해석에 사용
    elements_by_id: dict = None  # type: dict[int, dict]

    def __post_init__(self):
        if self.elements_by_id is None:
            self.elements_by_id = {}


# ── SOM 오버레이 드로잉 ────────────────────────────────────────────

def _draw_som_overlay(raw_bytes: bytes, elements: list[dict]) -> bytes:
    """PIL로 스크린샷에 번호 배지 오버레이를 그린다."""
    from PIL import Image, ImageDraw, ImageFont

    img     = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    # 종류별 테두리 색상 (RGBA)
    COLOR = {
        "button":   (220,  50,  50, 180),  # 빨강
        "link":     ( 50, 100, 220, 180),  # 파랑
        "checkbox": ( 50, 180,  50, 180),  # 초록
        "input":    (160,  80, 220, 180),  # 보라
        "select":   (220, 140,  40, 180),  # 주황
    }
    DEFAULT_COLOR = (120, 120, 120, 180)

    # 폰트 로드 (macOS 기본 → 실패 시 PIL default)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 11)
    except Exception:
        try:
            font = ImageFont.load_default(size=10)
        except Exception:
            font = ImageFont.load_default()

    for el in elements:
        color  = COLOR.get(el["kind"], DEFAULT_COLOR)
        label  = str(el["id"])

        # 반투명 테두리 박스
        draw.rectangle(
            [el["left"], el["top"], el["right"], el["bottom"]],
            outline=color[:3] + (220,),
            width=2,
        )

        # 번호 배지 (좌상단 모서리)
        R  = 9
        bx = el["left"] + R
        by = el["top"]  + R
        bx = max(R + 1, min(bx, img.width  - R - 1))
        by = max(R + 1, min(by, img.height - R - 1))

        draw.ellipse(
            [bx - R, by - R, bx + R, by + R],
            fill=color[:3] + (230,),
        )

        # 번호 텍스트
        try:
            tb = draw.textbbox((0, 0), label, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
        except Exception:
            tw, th = len(label) * 6, 10
        draw.text(
            (bx - tw // 2, by - th // 2 - 1),
            label,
            fill=(255, 255, 255, 255),
            font=font,
        )

    # 원본에 오버레이 합성 → RGB PNG
    combined = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    combined.save(buf, format="PNG")
    return buf.getvalue()


def _build_element_map(elements: list[dict]) -> str:
    """LLM에게 전달할 요소 목록 텍스트를 생성한다."""
    if not elements:
        return "(인터랙티브 요소 없음)"
    lines = [
        "## SOM 인터랙티브 요소 (스크린샷 번호 배지와 대응)",
        "[번호] 종류 | 텍스트 | 중심좌표(x,y)",
    ]
    for el in elements:
        text = el["text"] or "(텍스트 없음)"
        lines.append(f"[{el['id']}] {el['kind']} | {text} | ({el['x']}, {el['y']})")
    lines.append("\n※ CLICK (x, y) 시 위 좌표를 그대로 사용하세요.")
    return "\n".join(lines)


# ── perceive ──────────────────────────────────────────────────────

async def perceive(page: Page) -> ScreenState:
    """
    현재 페이지의 스크린샷을 찍어 ScreenState로 반환한다.

    SOM_MODE=1: DOM에서 인터랙티브 요소를 추출 → 스크린샷에 번호 오버레이 추가.
    SOM_MODE=0 (기본): 순수 비전 — 오버레이 없는 원본 스크린샷만 사용.
    """
    vp = page.viewport_size or {"width": 1280, "height": 800}
    width, height = vp["width"], vp["height"]

    # ① 스크린샷 캡처
    try:
        raw_bytes = await page.screenshot(full_page=False, timeout=30000)
    except Exception:
        # 페이지 로딩 중 또는 응답 없음 → 재시도
        await page.wait_for_timeout(3000)
        try:
            raw_bytes = await page.screenshot(full_page=False, timeout=20000)
        except Exception:
            # 최후 수단: 빈 흰 이미지 (에이전트가 WAIT 선택하도록)
            from PIL import Image as _Img
            img = _Img.new("RGB", (width, height), color=(255, 255, 255))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            raw_bytes = buf.getvalue()

    element_map    = ""
    elements_by_id: dict = {}

    # ② SOM 오버레이 (SOM_MODE=1일 때만)
    if _SOM_MODE:
        try:
            elements: list[dict] = await page.evaluate(_JS_GET_INTERACTIVE)
        except Exception:
            elements = []

        if elements:
            raw_bytes   = _draw_som_overlay(raw_bytes, elements)
            element_map = _build_element_map(elements)
            # id → 좌표 딕셔너리 구성 (executor에서 Click [N] 해석용)
            elements_by_id = {
                el["id"]: {"x": el["x"], "y": el["y"],
                           "kind": el["kind"], "text": el["text"]}
                for el in elements
            }

    screenshot_b64 = base64.standard_b64encode(raw_bytes).decode()

    # ③ 디버그: 스크린샷 파일 저장 (SOM_DEBUG_DIR 환경변수 설정 시)
    if _DEBUG_DIR:
        global _debug_counter
        _debug_counter += 1
        os.makedirs(_DEBUG_DIR, exist_ok=True)
        out_path = os.path.join(_DEBUG_DIR, f"step_{_debug_counter:03d}.png")
        with open(out_path, "wb") as f:
            f.write(raw_bytes)

    return ScreenState(
        screenshot_b64=screenshot_b64,
        page_title=await page.title(),
        page_url=page.url,
        width=width,
        height=height,
        element_map=element_map,
        elements_by_id=elements_by_id,
    )
