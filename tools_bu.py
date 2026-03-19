"""
tools_bu.py — browser-use BUPage용 Danawa 툴 어댑터

tools.py의 JS 로직을 그대로 재사용하되,
browser_use.actor.page.Page (CDP 기반)에서 동작하도록 래핑.

BUPage.evaluate()는 결과를 JSON 문자열로 반환 → json.loads() 필요.
"""

import json
from browser_use.actor.page import Page as BUPage

# tools.py에서 JS 스니펫 임포트
from tools import (
    _JS_SELECT_CATEGORY,
    _JS_TYPE_IN_SEARCH,
    _JS_SELECT_SEARCH_TAB,
    _JS_SORT_CHEAPEST,
    _JS_GET_PRODUCTS,
    _JS_ADD_PRODUCT,
    _JS_REMOVE_PART,
    _JS_APPLY_FILTER,
    _JS_CLEAR_FILTERS,
    _JS_GET_CART,
)


async def _eval(page: BUPage, js: str, *args) -> dict | list:
    """BUPage.evaluate() 결과를 dict/list로 파싱해서 반환."""
    result_str = await page.evaluate(js, *args)
    if not result_str:
        return {}
    try:
        return json.loads(result_str)
    except json.JSONDecodeError:
        return {"ok": False, "error": result_str}


async def tool_select_category(page: BUPage, name: str) -> str:
    result = await _eval(page, _JS_SELECT_CATEGORY, name)
    if result.get("ok"):
        await page.evaluate("() => new Promise(r => setTimeout(r, 600))")
        return f"카테고리 '{result['clicked']}' 선택 완료"
    return f"에러: {result.get('error')}"


async def tool_search(page: BUPage, query: str) -> str:
    result = await _eval(page, _JS_TYPE_IN_SEARCH, query)
    if not result.get("ok"):
        return f"에러: {result.get('error', '알 수 없는 오류')}"

    await page.evaluate("() => new Promise(r => setTimeout(r, 1500))")

    active_cat = result.get("activeCat", "")
    tab_result = await _eval(page, _JS_SELECT_SEARCH_TAB, active_cat)
    await page.evaluate("() => new Promise(r => setTimeout(r, 1000))")

    if tab_result.get("ok"):
        return (
            f"'{query}' 검색 완료 → '{tab_result['selected']}' 탭 자동 선택됨. "
            "바로 sort_cheapest → get_products → add_product 진행."
        )
    reason = tab_result.get("reason", "")
    if "단일 카테고리" in reason or "라디오 버튼 없음" in reason:
        return (
            f"'{query}' 검색 완료 (단일 카테고리 결과). "
            "바로 sort_cheapest → get_products → add_product 진행."
        )
    avail = tab_result.get("available", [])
    return f"'{query}' 검색 완료 (탭 선택 실패: {reason}). 가능한 탭: {avail}"


async def tool_sort_cheapest(page: BUPage) -> str:
    result = await _eval(page, _JS_SORT_CHEAPEST)
    if result.get("ok"):
        await page.evaluate("() => new Promise(r => setTimeout(r, 2000))")
        return f"낮은 가격순 정렬 완료 ({result.get('method', '?')}). TOOL get_products로 확인하세요."
    return f"에러: {result.get('error')}"


async def tool_get_products(page: BUPage, max_n: int = 10) -> str:
    products = await _eval(page, _JS_GET_PRODUCTS, max_n)
    if not products:
        return "제품 목록 없음 (검색 결과가 없거나 아직 로딩 중)"
    lines = []
    for p in products:
        added_mark = " ✓담김" if p.get("added") else ""
        spec_part = f"  [{p['spec']}]" if p.get("spec") else ""
        lines.append(f"  [{p['n']}] {p['name']}{spec_part}  |  {p['price']}{added_mark}")
    return "현재 제품 목록 (광고 제외):\n" + "\n".join(lines)


async def tool_add_product(page: BUPage, n: int = 1) -> str:
    result = await _eval(page, _JS_ADD_PRODUCT, n)
    if result.get("ok"):
        if result.get("already"):
            return f"이미 담긴 제품 (n={n})"
        await page.evaluate("() => new Promise(r => setTimeout(r, 500))")
        return f"담기 완료 | 이름:{result['name']} | 가격:{result.get('price', 0)}"
    return f"에러: {result.get('error')}"


async def tool_remove_part(page: BUPage, category: str) -> str:
    result = await _eval(page, _JS_REMOVE_PART, category)
    if result.get("ok"):
        await page.evaluate("() => new Promise(r => setTimeout(r, 500))")
        return f"'{category}' 부품 삭제 완료"
    avail = result.get("available", [])
    return f"에러: {result.get('error')} | 발견된 삭제버튼: {avail[:3]}"


async def tool_filter(page: BUPage, label: str) -> str:
    result = await _eval(page, _JS_APPLY_FILTER, label)
    if result.get("already"):
        return f"'{label}' 필터 이미 선택됨"
    if result.get("ok"):
        await page.evaluate("() => new Promise(r => setTimeout(r, 800))")
        return f"'{result['label']}' 필터 적용 완료"
    return f"에러: {result['error']} | 가능한 필터: {result.get('available', [])[:8]}"


async def tool_clear_filters(page: BUPage) -> str:
    result = await _eval(page, _JS_CLEAR_FILTERS)
    await page.evaluate("() => new Promise(r => setTimeout(r, 600))")
    return f"필터 {result.get('cleared', 0)}개 해제 완료"


async def tool_get_cart(page: BUPage) -> str:
    result = await _eval(page, _JS_GET_CART)
    if result.get("ok") and result.get("items"):
        lines = "\n".join(f"  - {item}" for item in result["items"])
        return f"현재 견적 패널:\n{lines}"
    return f"패널 현황 확인 실패: {result.get('text', '알 수 없음')}"
