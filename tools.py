"""
tools.py — Danawa 전용 DOM 기반 Tool 모음 (WALT 스타일)

LLM이 TOOL 명령으로 호출 → JS로 직접 DOM 요소를 찾아 실행.
좌표 추론 없이 신뢰성 높은 액션 보장.

Tool 목록:
  TOOL select_category "CPU"      ← 카테고리 선택
  TOOL search "i3-12100"          ← 검색창 입력 + 엔터
  TOOL sort_cheapest              ← 낮은 가격순 탭 클릭
  TOOL get_products               ← 광고 제외 제품 목록 반환
  TOOL add_product 1              ← n번째 비광고 제품 담기
  TOOL remove_part "메인보드"      ← 오른쪽 패널에서 부품 삭제 (X 버튼)
  TOOL get_cart                   ← 현재 오른쪽 패널 견적 현황 반환
"""

import json
from playwright.async_api import Page


# ── JS 스니펫 모음 ─────────────────────────────────────────────────

_JS_SELECT_CATEGORY = """
(name) => {
    // PC 주요구성 패널(오른쪽) 또는 견적 목록(왼쪽) 에서 카테고리 텍스트 매칭
    const candidates = Array.from(document.querySelectorAll(
        '.estimate_category li, .pc_main_wrap li, .pc_category li, ' +
        '.estimate_list li, dl.category_list dt, dl dd, ' +
        'ul li a, div[class*="category"] a, div[class*="part"] a'
    ));
    // 정확 일치 우선, 그 다음 포함 일치
    let target = candidates.find(el => el.textContent.trim() === name);
    if (!target) target = candidates.find(el => el.textContent.trim().includes(name));
    if (!target) {
        // 마지막 수단: 모든 클릭 가능한 요소에서 텍스트 탐색
        const all = Array.from(document.querySelectorAll('a, button, li, span, dt, dd'));
        target = all.find(el => el.children.length <= 2 && el.textContent.trim() === name);
    }
    if (!target) return { ok: false, error: `카테고리 '${name}' 못 찾음` };
    target.click();
    return { ok: true, clicked: target.textContent.trim() };
}
"""

_JS_GET_SEARCH_INPUT = """
() => {
    // 다나와 제품 검색창 — placeholder로 식별
    const inputs = Array.from(document.querySelectorAll('input[type="text"], input[type="search"], input:not([type])'));
    const priorities = ['상품명', '검색', 'search', '모델', '제품'];
    for (const kw of priorities) {
        const found = inputs.find(inp =>
            (inp.placeholder || '').toLowerCase().includes(kw.toLowerCase())
        );
        if (found) return { ok: true, placeholder: found.placeholder };
    }
    // 마지막 수단: 보이는 input 중 가장 넓은 것
    const visible = inputs.filter(inp => inp.offsetParent !== null && inp.offsetWidth > 100);
    if (visible.length) return { ok: true, placeholder: visible[0].placeholder || '' };
    return { ok: false, error: '검색창 못 찾음' };
}
"""

_JS_TYPE_IN_SEARCH = """
(query) => {
    const inputs = Array.from(document.querySelectorAll('input[type="text"], input[type="search"], input:not([type])'));
    const priorities = ['상품명', '검색', 'search', '모델', '제품'];
    let inp = null;
    for (const kw of priorities) {
        inp = inputs.find(i => (i.placeholder || '').toLowerCase().includes(kw.toLowerCase()));
        if (inp) break;
    }
    if (!inp) {
        const visible = inputs.filter(i => i.offsetParent !== null && i.offsetWidth > 100);
        inp = visible[0] || null;
    }
    if (!inp) return { ok: false, error: '검색창 못 찾음' };
    inp.focus();
    inp.value = '';
    inp.value = query;
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new Event('change', { bubbles: true }));
    return { ok: true };
}
"""

_JS_SORT_CHEAPEST = """
() => {
    // "낮은 가격순" 탭/버튼 찾기
    const all = Array.from(document.querySelectorAll('a, button, li, span'));
    const target = all.find(el =>
        el.textContent.trim() === '낮은 가격순' ||
        el.textContent.trim() === '낮은가격순'
    );
    if (!target) return { ok: false, error: '"낮은 가격순" 버튼 못 찾음' };
    target.click();
    return { ok: true };
}
"""

_JS_GET_PRODUCTS = """
(max_n) => {
    // TR 중 productList_ 클래스를 가진 것 → 광고(recom_area) 제외
    const allRows = Array.from(document.querySelectorAll('tr[class*="productList_"]'));
    const realRows = allRows.filter(tr => !tr.classList.contains('recom_area'));

    return realRows.slice(0, max_n).map((tr, i) => {
        // 제품명
        const nameEl =
            tr.querySelector('a.goods_name') ||
            tr.querySelector('a[class*="name"]') ||
            tr.querySelector('.prod_name a') ||
            tr.querySelector('td.description a') ||
            tr.querySelector('a[href*="product"]');

        // 스펙 요약 (제품명 아래 한 줄 설명)
        const specEl =
            tr.querySelector('.spec_list') ||
            tr.querySelector('.item_explain') ||
            tr.querySelector('td.description p') ||
            tr.querySelector('.goods_description');

        // 가격
        const priceEl =
            tr.querySelector('.price_sect .num') ||
            tr.querySelector('[class*="price"] .num') ||
            tr.querySelector('.num') ||
            tr.querySelector('[class*="price"]');

        // 이미 담긴 여부
        const btn = tr.querySelector('.btn_choice2.wishAction');
        const added = btn ? btn.textContent.trim() === '해제' : false;

        const name = nameEl ? nameEl.textContent.trim().slice(0, 80) : '(제품명 없음)';
        const spec = specEl ? specEl.textContent.trim().slice(0, 60) : '';
        const price = priceEl ? priceEl.textContent.trim().replace(/\\s+/g, '') : '(가격 없음)';

        return { n: i + 1, name, spec, price, added };
    });
}
"""

_JS_ADD_PRODUCT = """
(n) => {
    // 광고(recom_area) 제외한 실제 제품 담기 버튼
    const allBtns = Array.from(document.querySelectorAll('.btn_choice2.wishAction'));
    const realBtns = allBtns.filter(btn => {
        const row = btn.closest('tr');
        return row && !row.classList.contains('recom_area');
    });

    if (realBtns.length === 0) return { ok: false, error: '담기 버튼 없음 (제품 목록 비어있음)' };
    if (realBtns.length < n) return { ok: false, error: `제품 ${realBtns.length}개뿐 (${n}번째 요청)` };

    const btn = realBtns[n - 1];
    const row = btn.closest('tr');

    // 이미 담긴 제품인지 확인 (해제 버튼이면 이미 담긴 것)
    if (btn.textContent.trim() === '해제') {
        return { ok: true, name: '(이미 담긴 제품)', already: true };
    }

    // 제품명 추출
    const nameEl =
        row?.querySelector('a.goods_name') ||
        row?.querySelector('a[class*="name"]') ||
        row?.querySelector('.prod_name a') ||
        row?.querySelector('td.description a');
    const name = nameEl ? nameEl.textContent.trim().slice(0, 80) : '?';

    // 가격 추출
    const priceEl = row?.querySelector('.price_sect .num') || row?.querySelector('.num');
    const priceText = priceEl ? priceEl.textContent.replace(/[^0-9]/g, '') : '0';

    btn.click();
    return { ok: true, name, price: parseInt(priceText) || 0 };
}
"""


# ── Tool 실행 함수 ─────────────────────────────────────────────────

async def tool_select_category(page: Page, name: str) -> str:
    """왼쪽/오른쪽 카테고리 목록에서 이름으로 카테고리 선택"""
    result = await page.evaluate(_JS_SELECT_CATEGORY, name)
    if result["ok"]:
        await page.wait_for_timeout(600)
        return f"카테고리 '{result['clicked']}' 선택 완료"
    return f"에러: {result['error']}"


async def tool_search(page: Page, query: str) -> str:
    """현재 페이지 검색창에 쿼리 입력 후 엔터"""
    result = await page.evaluate(_JS_TYPE_IN_SEARCH, query)
    if result["ok"]:
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("domcontentloaded", timeout=8000)
        await page.wait_for_timeout(500)
        return f"'{query}' 검색 완료"
    return f"에러: {result.get('error', '알 수 없는 오류')}"


async def tool_sort_cheapest(page: Page) -> str:
    """낮은 가격순 정렬 탭 클릭"""
    result = await page.evaluate(_JS_SORT_CHEAPEST)
    if result["ok"]:
        await page.wait_for_timeout(600)
        return "낮은 가격순 정렬 완료"
    return f"에러: {result.get('error')}"


async def tool_get_products(page: Page, max_n: int = 10) -> str:
    """
    현재 페이지의 실제 제품 목록 텍스트 반환 (광고 제외).
    LLM이 제품 목록을 보고 n번째 선택 결정에 활용.
    """
    products = await page.evaluate(_JS_GET_PRODUCTS, max_n)
    if not products:
        return "제품 목록 없음 (검색 결과가 없거나 아직 로딩 중)"
    lines = []
    for p in products:
        added_mark = " ✓담김" if p.get("added") else ""
        spec_part = f"  [{p['spec']}]" if p.get("spec") else ""
        lines.append(f"  [{p['n']}] {p['name']}{spec_part}  |  {p['price']}{added_mark}")
    return "현재 제품 목록 (광고 제외) — add_product N으로 담기:\n" + "\n".join(lines)


async def tool_add_product(page: Page, n: int = 1) -> str:
    """
    n번째 실제 제품(광고 recom_area 제외)의 담기 버튼 클릭.
    성공 시 제품명·가격 반환.
    """
    result = await page.evaluate(_JS_ADD_PRODUCT, n)
    if result["ok"]:
        if result.get("already"):
            return f"이미 담긴 제품 (n={n})"
        await page.wait_for_timeout(500)
        return (
            f"담기 완료 | 이름:{result['name']} | 가격:{result.get('price', 0)}"
        )
    return f"에러: {result.get('error')}"


_JS_REMOVE_PART = """
(categoryName) => {
    // 오른쪽 PC 주요구성 패널에서 카테고리명으로 행을 찾아 X 버튼 클릭
    // 패널 구조: 각 부품 행에 카테고리 레이블 + 제품명 + X(삭제) 버튼
    const allEls = Array.from(document.querySelectorAll('*'));

    // X / 삭제 버튼 패턴: 'x', '×', '✕', '닫기', 'del', 'remove', 'close'
    const deleteBtns = Array.from(document.querySelectorAll(
        'a[class*="del"], button[class*="del"], a[class*="close"], button[class*="close"], ' +
        'a[class*="remove"], a[class*="cancel"], span[class*="del"], ' +
        '.estimate_list .del, .pc_result .del, .selected_item .del'
    ));

    // 카테고리명을 포함하는 부모 행에서 삭제 버튼 탐색
    const nameMap = {
        'CPU': 'CPU', '메인보드': '메인보드', '메모리': '메모리', 'RAM': '메모리',
        'SSD': 'SSD', 'HDD': 'HDD', '케이스': '케이스', '파워': '파워',
        '그래픽카드': '그래픽카드', 'GPU': '그래픽카드'
    };
    const target = nameMap[categoryName] || categoryName;

    // 방법 1: 삭제 버튼 주변 텍스트에서 카테고리명 매칭
    for (const btn of deleteBtns) {
        const container = btn.closest('li, tr, div[class*="item"], div[class*="part"], p');
        if (container && container.textContent.includes(target)) {
            btn.click();
            return { ok: true, method: 'del-class', category: target };
        }
    }

    // 방법 2: X 텍스트를 가진 모든 링크/버튼 탐색
    const xBtns = allEls.filter(el => {
        const t = el.textContent.trim();
        return (t === 'X' || t === 'x' || t === '×' || t === '✕') &&
               ['A', 'BUTTON', 'SPAN'].includes(el.tagName);
    });
    for (const btn of xBtns) {
        const container = btn.closest('li, tr, div, p');
        if (container && container.textContent.includes(target)) {
            btn.click();
            return { ok: true, method: 'x-text', category: target };
        }
    }

    // 방법 3: onclick 속성에 'del' / 'remove' 포함된 요소
    const onclickEls = allEls.filter(el =>
        (el.getAttribute('onclick') || '').match(/del|remove|cancel/i)
    );
    for (const btn of onclickEls) {
        const container = btn.closest('li, tr, div, p');
        if (container && container.textContent.includes(target)) {
            btn.click();
            return { ok: true, method: 'onclick', category: target };
        }
    }

    // 실패 시 현재 패널의 삭제 가능한 버튼 목록 반환 (디버깅용)
    const available = deleteBtns.slice(0, 5).map(b => ({
        tag: b.tagName,
        cls: b.className,
        parentText: b.closest('li, tr, div')?.textContent?.trim()?.slice(0, 40)
    }));
    return { ok: false, error: `'${target}' 행의 삭제 버튼 못 찾음`, available };
}
"""

_JS_GET_CART = """
() => {
    // 오른쪽 PC 주요구성 패널 현황 텍스트 수집
    const panel =
        document.querySelector('.pc_result') ||
        document.querySelector('.estimate_result') ||
        document.querySelector('[class*="cart"]') ||
        document.querySelector('[class*="result"]');

    if (!panel) return { ok: false, text: '패널 못 찾음' };

    // 각 부품 행의 카테고리 + 제품명 + 가격
    const items = Array.from(panel.querySelectorAll('li, tr, [class*="item"]'))
        .filter(el => el.textContent.trim().length > 3)
        .slice(0, 15)
        .map(el => el.textContent.trim().replace(/\\s+/g, ' ').slice(0, 80));

    return { ok: true, items };
}
"""


async def tool_remove_part(page: Page, category: str) -> str:
    """
    오른쪽 PC 주요구성 패널에서 카테고리명으로 부품 삭제 (X 버튼 DOM 클릭).
    좌표 클릭 없이 신뢰성 높게 처리.
    """
    result = await page.evaluate(_JS_REMOVE_PART, category)
    if result["ok"]:
        await page.wait_for_timeout(500)
        return f"'{category}' 부품 삭제 완료 (방법: {result.get('method')})"
    # 실패 시 사용 가능한 버튼 목록 포함해서 반환
    avail = result.get("available", [])
    avail_str = ", ".join(str(a) for a in avail[:3]) if avail else "없음"
    return f"에러: {result.get('error')} | 발견된 삭제버튼: {avail_str}"


async def tool_get_cart(page: Page) -> str:
    """오른쪽 패널의 현재 견적 현황을 텍스트로 반환."""
    result = await page.evaluate(_JS_GET_CART)
    if result["ok"] and result.get("items"):
        lines = "\n".join(f"  - {item}" for item in result["items"])
        return f"현재 견적 패널:\n{lines}"
    return f"패널 현황 확인 실패: {result.get('text', '알 수 없음')}"


# ── 디스패처 ────────────────────────────────────────────────────────

TOOL_REGISTRY = {
    "select_category": tool_select_category,
    "search":          tool_search,
    "sort_cheapest":   tool_sort_cheapest,
    "get_products":    tool_get_products,
    "add_product":     tool_add_product,
    "remove_part":     tool_remove_part,
    "get_cart":        tool_get_cart,
}


async def execute_tool(tool_name: str, args_str: str, page: Page) -> str:
    """
    TOOL 명령을 파싱해서 해당 함수 호출.

    args_str 예시:
      "CPU"   → str
      "1"     → int (add_product용)
      ""      → 인자 없음
    """
    fn = TOOL_REGISTRY.get(tool_name.lower())
    if fn is None:
        known = ", ".join(TOOL_REGISTRY.keys())
        return f"알 수 없는 Tool: '{tool_name}'. 사용 가능: {known}"

    # 인자 파싱
    args_str = (args_str or "").strip().strip('"').strip("'").strip()

    if tool_name.lower() == "add_product":
        n = int(args_str) if args_str.isdigit() else 1
        return await fn(page, n)
    elif tool_name.lower() == "get_products":
        n = int(args_str) if args_str.isdigit() else 10
        return await fn(page, n)
    elif tool_name.lower() in ("remove_part", "select_category", "search"):
        return await fn(page, args_str)
    elif args_str:
        return await fn(page, args_str)
    else:
        return await fn(page)
