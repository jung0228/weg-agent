"""
tools.py — Danawa 전용 DOM 기반 Tool 모음 (WALT 스타일)

LLM이 TOOL 명령으로 호출 → JS로 직접 DOM 요소를 찾아 실행.
좌표 추론 없이 신뢰성 높은 액션 보장.

Tool 목록:
  TOOL select_category "CPU"           ← 카테고리 선택
  TOOL filter "인텔(소켓1700)"          ← 필터 체크박스 클릭 (텍스트 매칭)
  TOOL filter "DDR4"                   ← 필터 체크박스 클릭
  TOOL clear_filters                   ← 현재 카테고리 필터 전체 해제
  TOOL search "i3-12100"               ← 검색창 입력 (카테고리 내 검색)
  TOOL sort_cheapest                   ← 낮은 가격순 탭 클릭
  TOOL get_products                    ← 광고 제외 제품 목록 반환
  TOOL add_product 1                   ← n번째 비광고 제품 담기
  TOOL remove_part "메인보드"           ← 오른쪽 패널에서 부품 삭제
  TOOL get_cart                        ← 현재 오른쪽 패널 견적 현황 반환
"""

import json
from playwright.async_api import Page


# ── JS 스니펫 모음 ─────────────────────────────────────────────────

_JS_SELECT_CATEGORY = """
(name) => {
    // 실제 DOM: dd.category_XXX.pd_item > a.pd_item_title
    // onclick="category(ID, 2)" 형태로 카테고리 전환

    // 카테고리명 → category ID 매핑 (DOM 분석으로 확인된 값)
    const NAME_TO_ID = {
        'CPU': 873,
        '쿨러': 887, '쿨러/튜닝': 887, '쿨러튜닝': 887,
        '메인보드': 875,
        '메모리': 874, 'RAM': 874,
        '그래픽카드': 876, 'GPU': 876, 'VGA': 876,
        'SSD': 32617,
        'HDD': 877,
        '케이스': 879,
        '파워': 880,
        '소프트웨어': 901,
        '모니터': 13735,
    };

    const catId = NAME_TO_ID[name];
    if (catId) {
        // 방법 1: category() JS 전역 함수 직접 호출
        if (typeof category === 'function') {
            category(catId, 2);
            return { ok: true, clicked: name, method: 'js-func' };
        }
        // 방법 2: dd.category_ID > a 클릭
        const btn = document.querySelector(`dd.category_${catId} a.pd_item_title`);
        if (btn) {
            btn.click();
            return { ok: true, clicked: name, method: 'dom-click' };
        }
    }

    // 방법 3: dd[class*="pd_item"] 안에서 텍스트 매칭 fallback
    const allLinks = Array.from(document.querySelectorAll('dd[class*="pd_item"] a'));
    const target = allLinks.find(a => {
        const ddText = a.closest('dd')?.textContent?.trim() ?? '';
        return a.textContent.trim() === name || ddText.startsWith(name);
    });
    if (target) {
        target.click();
        return { ok: true, clicked: name, method: 'text-match' };
    }

    return { ok: false, error: `카테고리 '${name}' 못 찾음 (ID 매핑 없음, 텍스트 매칭 실패)` };
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
    // 실제 DOM: #searchProduct + button.btn_search 클릭 (Enter는 전체 사이트 검색으로 이탈)
    let inp = document.querySelector('#searchProduct');
    if (!inp) {
        const inputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'));
        inp = inputs.find(i => (i.placeholder || '').includes('상품명'));
    }
    if (!inp) return { ok: false, error: '검색창(#searchProduct) 못 찾음' };

    inp.focus();
    inp.value = '';
    inp.value = query;
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new Event('change', { bubbles: true }));

    // 현재 선택된 카테고리 이름 파악 (오른쪽 패널 .select)
    const activeDd = document.querySelector('dd[class*="pd_item"].select');
    const activeCat = activeDd?.querySelector('a')?.textContent?.trim() || '';

    const searchBtn = document.querySelector('button.btn_search');
    if (searchBtn) searchBtn.click();

    return { ok: true, method: searchBtn ? 'btn_search' : 'input-only', activeCat };
}
"""

_JS_SELECT_SEARCH_TAB = """
(activeCat) => {
    // 검색 결과 탭(radio) 중 현재 카테고리와 일치하는 것 선택
    // 구조: input[name="serviceSectionSeq"] + label[for=ID] (텍스트: "메인보드(1)" 등)
    if (!activeCat) return { ok: false, reason: 'activeCat 없음' };

    const radios = Array.from(document.querySelectorAll('input[name="serviceSectionSeq"]'));
    if (!radios.length) return { ok: false, reason: '라디오 버튼 없음 (단일 카테고리 결과)' };

    for (const radio of radios) {
        const label = document.querySelector(`label[for="${radio.id}"]`);
        const labelText = label?.textContent?.trim() || '';
        if (labelText.startsWith(activeCat)) {
            radio.click();
            if (label) label.click();
            return { ok: true, selected: labelText };
        }
    }

    // 전체 중 count가 가장 적은 카테고리 라디오 선택 (가장 정확할 확률 높음)
    const nonAll = radios.filter(r => r.id !== 'result_all');
    if (nonAll.length === 1) {
        const label = document.querySelector(`label[for="${nonAll[0].id}"]`);
        nonAll[0].click();
        if (label) label.click();
        return { ok: true, selected: label?.textContent?.trim(), reason: '단독 비전체 탭' };
    }

    return { ok: false, reason: `'${activeCat}' 탭 못 찾음`, available: radios.map(r => document.querySelector(`label[for="${r.id}"]`)?.textContent?.trim()) };
}
"""

_JS_SORT_CHEAPEST = """
() => {
    // 방법 1: onclick에 GOODSINFO_CASH_PRICE_ASC 포함된 요소 클릭 (가장 정확)
    const onclickEl = Array.from(document.querySelectorAll('[onclick]')).find(el =>
        (el.getAttribute('onclick') || '').includes('CASH_PRICE_ASC')
    );
    if (onclickEl) {
        onclickEl.click();
        return { ok: true, method: 'onclick-ASC' };
    }

    // 방법 2: "낮은 가격순" 텍스트를 가진 li > a 요소 (정렬 탭)
    const sortLinks = Array.from(document.querySelectorAll('li a, ul a'));
    const target = sortLinks.find(el =>
        el.textContent.trim() === '낮은 가격순' ||
        el.textContent.trim() === '낮은가격순'
    );
    if (target) {
        target.click();
        return { ok: true, method: 'text-link' };
    }

    // 방법 3: 정렬 관련 버튼 중 텍스트 매칭
    const allEl = Array.from(document.querySelectorAll('button, a, span'));
    const btn = allEl.find(el =>
        el.textContent.trim() === '낮은 가격순' ||
        el.textContent.trim() === '낮은가격순'
    );
    if (btn) {
        btn.click();
        return { ok: true, method: 'text-click' };
    }

    return { ok: false, error: '"낮은 가격순" 버튼 못 찾음 (onclick-ASC, text-link, text-click 모두 실패)' };
}
"""

_JS_GET_PRODUCTS = """
(max_n) => {
    // TR 중 productList_ 클래스를 가진 것 → 광고(recom_area) 제외
    const allRows = Array.from(document.querySelectorAll('tr[class*="productList_"]'));
    const realRows = allRows.filter(tr => !tr.classList.contains('recom_area'));

    return realRows.slice(0, max_n).map((tr, i) => {
        // 제품명: td.title_price 내 빈 클래스 a 태그
        const nameEl =
            tr.querySelector('td.title_price a[class=""]') ||
            tr.querySelector('td.title_price .subject a') ||
            tr.querySelector('td.title_price a');

        // 스펙 요약: .spec 클래스 (spec_wrap 내부)
        const specEl =
            tr.querySelector('td.title_price .spec') ||
            tr.querySelector('td.title_price .spec_wrap');

        // 가격: .prod_price(숫자만) 또는 .low_price(원 포함)
        const priceEl =
            tr.querySelector('.prod_price') ||
            tr.querySelector('.low_price');

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
    // 광고(recom_area) 제외 + 중고 제품 제외한 실제 제품 목록
    const allBtns = Array.from(document.querySelectorAll('.btn_choice2.wishAction'));
    const realBtns = allBtns.filter(btn => {
        const row = btn.closest('tr');
        if (!row || row.classList.contains('recom_area')) return false;
        // 중고 제품 제외
        const rowText = row.textContent || '';
        if (rowText.includes('중고') || rowText.includes('리퍼') || rowText.includes('재생')) return false;
        return true;
    });

    if (realBtns.length === 0) {
        return { ok: false, error: '중고/리퍼 제외 후 담기 가능한 제품 없음 — 필터/카테고리 변경 필요' };
    }

    if (realBtns.length < n) return { ok: false, error: `제품 ${realBtns.length}개뿐 (${n}번째 요청, 중고제외)` };

    const btn = realBtns[n - 1];
    const row = btn.closest('tr');

    // 이미 담긴 제품인지 확인
    if (btn.textContent.trim() === '해제') {
        return { ok: true, name: '(이미 담긴 제품)', already: true };
    }

    // 제품명 추출
    const nameEl =
        row?.querySelector('td.title_price a[class=""]') ||
        row?.querySelector('td.title_price .subject a') ||
        row?.querySelector('td.title_price a');
    const name = nameEl ? nameEl.textContent.trim().slice(0, 80) : '?';

    // 가격 추출: .prod_price(숫자만) 또는 .low_price(원 포함)
    const priceEl = row?.querySelector('.prod_price') || row?.querySelector('.low_price');
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
    """카테고리 내 검색창(#searchProduct)에 쿼리 입력 → button.btn_search 클릭
    → 결과 탭이 여러 카테고리로 분리되면 현재 카테고리 탭 자동 선택.
    Enter 키는 전체 사이트 검색으로 이탈하므로 사용하지 않음."""
    result = await page.evaluate(_JS_TYPE_IN_SEARCH, query)
    if not result["ok"]:
        return f"에러: {result.get('error', '알 수 없는 오류')}"

    await page.wait_for_timeout(1500)  # 검색 결과 로딩 대기

    # 검색 결과가 여러 카테고리 탭으로 분리된 경우 → 현재 카테고리 탭 선택
    active_cat = result.get("activeCat", "")
    tab_result = await page.evaluate(_JS_SELECT_SEARCH_TAB, active_cat)
    await page.wait_for_timeout(1000)  # 탭 선택 후 로딩 대기 (충분히 기다려서 LLM이 탭 재클릭 안 하도록)

    if tab_result.get("ok"):
        return (
            f"'{query}' 검색 완료 → '{tab_result['selected']}' 탭 자동 선택됨. "
            "추가 탭 클릭 불필요. 바로 sort_cheapest → get_products → add_product 진행."
        )
    else:
        reason = tab_result.get("reason", "")
        if "단일 카테고리" in reason or "라디오 버튼 없음" in reason:
            return (
                f"'{query}' 검색 완료 (단일 카테고리 결과). "
                "바로 sort_cheapest → get_products → add_product 진행."
            )
        avail = tab_result.get("available", [])
        return f"'{query}' 검색 완료 (탭 선택 실패: {reason}). 가능한 탭: {avail}"


async def tool_sort_cheapest(page: Page) -> str:
    """낮은 가격순 정렬 탭 클릭"""
    result = await page.evaluate(_JS_SORT_CHEAPEST)
    if result["ok"]:
        # 정렬 후 AJAX/리로드 대기 — 페이지 navigation이 발생할 수 있으므로 load_state로 대기
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            # networkidle timeout은 무시 (AJAX 업데이트면 괜찮음)
            pass
        try:
            await page.wait_for_timeout(1000)
        except Exception:
            pass
        return f"낮은 가격순 정렬 완료 ({result.get('method', '?')}). 제품 목록이 갱신되었으니 TOOL get_products로 확인하세요."
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

_JS_APPLY_FILTER = """
(labelText) => {
    // 필터 체크박스 구조: span.item_checkbox > input[type=checkbox] + 텍스트노드
    // id 없음 → 텍스트 매칭으로 찾아서 클릭
    const items = Array.from(document.querySelectorAll('.item_checkbox'));
    const target = items.find(span => {
        const text = span.textContent.trim();
        return text === labelText || text.startsWith(labelText);
    });
    if (!target) {
        const available = items.slice(0, 15).map(s => s.textContent.trim());
        return { ok: false, error: `'${labelText}' 필터 못 찾음`, available };
    }
    const checkbox = target.querySelector('input[type="checkbox"]');
    if (!checkbox) return { ok: false, error: '체크박스 없음' };
    if (checkbox.checked) return { ok: true, already: true, label: labelText };
    checkbox.click();
    return { ok: true, label: target.textContent.trim(), checked: true };
}
"""

_JS_CLEAR_FILTERS = """
() => {
    // 선택된 모든 필터 해제
    const checked = Array.from(document.querySelectorAll('.item_checkbox input[type="checkbox"]:checked'));
    checked.forEach(cb => cb.click());

    // "전체 초기화" 버튼 있으면 클릭
    const resetBtn = Array.from(document.querySelectorAll('button, a'))
        .find(el => el.textContent.trim().includes('초기화') || el.textContent.trim().includes('전체해제'));
    if (resetBtn) resetBtn.click();

    return { ok: true, cleared: checked.length };
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


async def tool_filter(page: Page, label: str) -> str:
    """필터 체크박스 클릭 (span.item_checkbox 텍스트 매칭).
    예: TOOL filter "인텔(소켓1700)"  /  TOOL filter "DDR4"  /  TOOL filter "인텔" """
    result = await page.evaluate(_JS_APPLY_FILTER, label)
    if result.get("already"):
        return f"'{label}' 필터 이미 선택됨"
    if result["ok"]:
        await page.wait_for_timeout(800)
        return f"'{result['label']}' 필터 적용 완료"
    avail = result.get("available", [])
    return f"에러: {result['error']} | 가능한 필터: {avail[:8]}"


async def tool_clear_filters(page: Page) -> str:
    """현재 카테고리의 모든 필터 체크박스 해제."""
    result = await page.evaluate(_JS_CLEAR_FILTERS)
    await page.wait_for_timeout(600)
    return f"필터 {result.get('cleared', 0)}개 해제 완료"


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
    "filter":          tool_filter,
    "clear_filters":   tool_clear_filters,
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
    elif tool_name.lower() in ("remove_part", "select_category", "search", "filter"):
        return await fn(page, args_str)
    elif args_str:
        return await fn(page, args_str)
    else:
        return await fn(page)
