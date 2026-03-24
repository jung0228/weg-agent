"""
ui_explorer.py — 능동적 UI 탐색기 (Active UI Explorer)
Web-CogReasoner Factual Knowledge + Go-Browse inner loop 개념 적용

기존 문제:
  - 초기 스크린샷 한 장만 분석 → 클릭 후 어떻게 변하는지 모름
  - 스크롤 영역 파악 못함 → 숨겨진 콘텐츠 미발견

4단계 능동 탐색:
  Phase 1. 초기 상태 (overview)
    - 스크린샷 + DOM 샘플로 기본 레이아웃 파악

  Phase 2. 카테고리 클릭 탐색 (state transitions)
    - 6개 카테고리(CPU/메인보드/메모리/SSD/케이스/파워)를 순서대로 클릭
    - 각각 before/after 스크린샷 비교 → 상태 전이 기록

  Phase 3. 스크롤 탐색 (scroll discovery)
    - 제품 목록 세로 스크롤 → 추가 제품 확인
    - 오른쪽 패널 세로 스크롤 → 숨겨진 섹션 확인
    - 가로 스크롤 영역 탐지

  Phase 4. 인터랙션 탐색 (interaction patterns)
    - 검색창 테스트 → 검색 결과 구조 확인
    - 담기 버튼 확인

  최종 합성: 모든 관찰 → DanawaKnowledge (state_transitions + scroll_areas 포함)

사용:
  python ui_explorer.py               # 전체 탐색 실행
  python ui_explorer.py --phase 2     # 특정 단계만
  python ui_explorer.py --no-save     # 결과 저장 안 함
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import openai
from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page

from knowledge import (
    BASE_KNOWLEDGE, DanawaKnowledge, UIElement, UIRegion,
    UIStateTransition, ScrollArea,
    CACHE_PATH, save_knowledge,
)

load_dotenv()

DANAWA_ESTIMATE_URL = "https://shop.danawa.com/virtualestimate/?controller=estimateMain&methods=index&marketPlaceSeq=16"
MODEL = "gemini-3-flash-preview"
LETSUR_BASE_URL = "https://gateway.letsur.ai/v1"

CATEGORIES = ["CPU", "메인보드", "메모리", "SSD", "케이스", "파워"]


# ── 유틸리티 ─────────────────────────────────────────────────────────

async def _screenshot_b64(page: Page) -> str:
    raw = await page.screenshot(full_page=False)
    return base64.standard_b64encode(raw).decode()


def _img_msg(b64: str) -> dict:
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}


def _text_msg(text: str) -> dict:
    return {"type": "text", "text": text}


def _llm_call(client: openai.OpenAI, system: str, user_content: list[dict], max_tokens: int = 1200) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    )
    return resp.choices[0].message.content.strip()


def _parse_json(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        return json.loads(cleaned)
    except Exception:
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {}


# ── DOM 샘플러 ────────────────────────────────────────────────────────

_JS_DOM_OVERVIEW = """
() => {
    const count = sel => document.querySelectorAll(sel).length;
    const safe = sel => {
        const el = document.querySelector(sel);
        return el ? el.outerHTML.slice(0, 150) : null;
    };
    const bbox = sel => {
        const el = document.querySelector(sel);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return {top: Math.round(r.top), left: Math.round(r.left),
                width: Math.round(r.width), height: Math.round(r.height)};
    };
    return {
        url: location.href,
        title: document.title.slice(0, 60),
        viewport: {w: window.innerWidth, h: window.innerHeight},
        // 스크롤 가능 영역 탐지
        scrollable_elements: Array.from(document.querySelectorAll('*'))
            .filter(el => {
                const s = window.getComputedStyle(el);
                return (s.overflow === 'auto' || s.overflow === 'scroll' ||
                        s.overflowY === 'auto' || s.overflowY === 'scroll' ||
                        s.overflowX === 'auto' || s.overflowX === 'scroll') &&
                       el.scrollHeight > el.clientHeight + 10;
            })
            .slice(0, 8)
            .map(el => ({
                tag: el.tagName,
                id: el.id.slice(0, 30),
                cls: el.className.slice(0, 60),
                scrollH: el.scrollHeight,
                clientH: el.clientHeight,
                bbox: (() => { const r = el.getBoundingClientRect();
                    return {top: Math.round(r.top), left: Math.round(r.left),
                            w: Math.round(r.width), h: Math.round(r.height)}; })()
            })),
        // 카테고리 버튼 — 실제 DOM: dd.category_XXX.pd_item > a.pd_item_title
        category_btns: Array.from(document.querySelectorAll(
            'dd[class*="pd_item"] a.pd_item_title'
        )).slice(0, 12).map(el => ({
            text: el.closest('dd')?.textContent?.trim()?.split('\\n')[0]?.trim()?.slice(0, 20) || el.textContent.trim().slice(0, 20),
            cls: el.closest('dd')?.className?.slice(0, 60),
            onclick: (el.getAttribute('onclick') || '').slice(0, 80),
            bbox: (() => { const r = el.getBoundingClientRect();
                return {x: Math.round(r.left + r.width/2),
                        y: Math.round(r.top + r.height/2)}; })()
        })),
        // 검색창 (실제: #searchProduct)
        search_input_id: document.querySelector('#searchProduct') ? '#searchProduct' : null,
        // 제품 행
        product_rows_total: count('tr[class*="productList"]'),
        product_rows_ad: count('tr.recom_area'),
        product_sample: safe('tr[class*="productList"]:not(.recom_area)'),
        // 핵심 버튼들
        add_btn: count('.btn_choice2.wishAction'),
        add_btn_sample: safe('.btn_choice2.wishAction'),
        sort_btn: count('[class*="sort"] a, [onclick*="sort"]'),
        search_input: safe('input[type="text"]'),
    };
}
"""

_JS_SCROLL_CHECK = """
(selector) => {
    const el = selector ? document.querySelector(selector) : document.scrollingElement;
    if (!el) return {scrollable: false};
    return {
        scrollable: el.scrollHeight > el.clientHeight + 5,
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
        scrollTop: el.scrollTop,
        canScrollMore: el.scrollHeight - el.scrollTop - el.clientHeight > 10,
    };
}
"""


# ── Phase 1: 초기 상태 개요 ───────────────────────────────────────────

async def phase1_overview(page: Page, client: openai.OpenAI) -> dict:
    """초기 스크린샷 + DOM 분석 → 레이아웃 파악"""
    print("  [Phase 1] 초기 상태 분석...")
    before_b64 = await _screenshot_b64(page)
    dom = await page.evaluate(_JS_DOM_OVERVIEW)

    system = """\
다나와 PC견적 페이지의 초기 상태를 분석합니다.
스크린샷과 DOM 데이터를 보고 레이아웃을 JSON으로 출력하세요.

출력 형식:
{
  "regions": [
    {"name": "영역명", "location": "오른쪽/가운데/왼쪽/상단", "description": "역할"}
  ],
  "initial_state": "페이지 처음 로드 시 보이는 것 한 줄 요약",
  "scrollable_hint": "스크롤 가능해 보이는 영역들",
  "category_found": ["발견된 카테고리 버튼 텍스트 목록"]
}"""

    raw = _llm_call(client, system, [
        _img_msg(before_b64),
        _text_msg(f"DOM 샘플:\n```json\n{json.dumps(dom, ensure_ascii=False)}\n```"),
    ])
    result = _parse_json(raw)
    result["_screenshot"] = before_b64
    result["_dom"] = dom
    print(f"    → 카테고리 발견: {result.get('category_found', [])}")
    print(f"    → 초기 상태: {result.get('initial_state', '')[:60]}")
    return result


# ── Phase 2: 카테고리 클릭 탐색 ──────────────────────────────────────

_JS_SELECT_CATEGORY = """
(categoryName) => {
    // 실제 DOM: dd.category_XXX.pd_item > a.pd_item_title
    // onclick="category(ID,2)" 형태
    const NAME_TO_ID = {
        'CPU': 873, '쿨러': 887, '쿨러/튜닝': 887,
        '메인보드': 875, '메모리': 874,
        '그래픽카드': 876, 'SSD': 32617,
        'HDD': 877, '케이스': 879, '파워': 880,
    };
    const catId = NAME_TO_ID[categoryName];
    if (catId) {
        if (typeof category === 'function') {
            category(catId, 2);
            return {success: true, text: categoryName, method: 'js-func'};
        }
        const btn = document.querySelector(`dd.category_${catId} a.pd_item_title`);
        if (btn) { btn.click(); return {success: true, text: btn.textContent.trim(), method: 'dom-click'}; }
    }
    // fallback: 텍스트 매칭
    const links = Array.from(document.querySelectorAll('dd[class*="pd_item"] a'));
    const target = links.find(a => a.closest('dd')?.textContent?.trim().startsWith(categoryName));
    if (target) { target.click(); return {success: true, text: categoryName, method: 'text-match'}; }
    return {success: false, tried: links.map(a => a.textContent.trim()).slice(0, 10)};
}
"""


async def phase2_categories(page: Page, client: openai.OpenAI) -> list[UIStateTransition]:
    """각 카테고리 클릭 전후 상태 비교"""
    print("  [Phase 2] 카테고리 클릭 탐색...")
    transitions: list[UIStateTransition] = []

    # 카테고리 쌍 (CPU+메인보드만 실제 탐색, 나머지는 패턴 추론 — API 비용 절약)
    explore_cats = CATEGORIES[:3]  # CPU, 메인보드, 메모리만 직접 탐색

    # before/after 쌍 수집
    pairs: list[dict] = []
    for cat in explore_cats:
        before_b64 = await _screenshot_b64(page)
        before_dom_counts = await page.evaluate("""() => ({
            products: document.querySelectorAll('tr[class*="productList"]').length,
            add_btns: document.querySelectorAll('.btn_choice2.wishAction').length,
        })""")

        result = await page.evaluate(_JS_SELECT_CATEGORY, cat)
        if not result.get("success"):
            print(f"    ✗ '{cat}' 카테고리 버튼 못 찾음: {result.get('tried', [])}")
            continue

        await page.wait_for_timeout(1500)
        after_b64 = await _screenshot_b64(page)
        after_dom_counts = await page.evaluate("""() => ({
            products: document.querySelectorAll('tr[class*="productList"]').length,
            add_btns: document.querySelectorAll('.btn_choice2.wishAction').length,
            search_input: document.querySelectorAll('input[type="text"]').length,
        })""")

        pairs.append({
            "category": cat,
            "before_b64": before_b64,
            "after_b64": after_b64,
            "before_dom": before_dom_counts,
            "after_dom": after_dom_counts,
        })
        print(f"    ✓ '{cat}': 제품 {before_dom_counts['products']}→{after_dom_counts['products']}개, "
              f"담기버튼 {before_dom_counts['add_btns']}→{after_dom_counts['add_btns']}개")

    if not pairs:
        return transitions

    # 한 번의 LLM 호출로 모든 before/after 쌍 분석
    system = """\
다나와 PC견적에서 카테고리를 클릭했을 때 UI가 어떻게 변하는지 분석합니다.
각 카테고리별 before/after 스크린샷을 비교하여 상태 전이를 JSON으로 출력하세요.

출력 형식:
{
  "transitions": [
    {
      "category": "CPU",
      "from_state": "before 상태 설명 (한 줄)",
      "to_state": "after 상태 설명 (한 줄)",
      "key_finding": "가장 중요한 변화 (예: '가운데에 CPU 제품 목록 23개 나타남, 검색창 새로 표시')"
    }
  ],
  "common_pattern": "모든 카테고리에 공통적으로 적용되는 패턴"
}"""

    user_content = []
    for p in pairs:
        user_content.append(_text_msg(
            f"=== {p['category']} 클릭 ===\n"
            f"DOM 변화: 제품 {p['before_dom']['products']}→{p['after_dom']['products']}개, "
            f"담기버튼 {p['before_dom']['add_btns']}→{p['after_dom']['add_btns']}개"
        ))
        user_content.append(_img_msg(p["before_b64"]))
        user_content.append(_text_msg(f"↓ {p['category']} 클릭 후"))
        user_content.append(_img_msg(p["after_b64"]))

    raw = _llm_call(client, system, user_content, max_tokens=1000)
    data = _parse_json(raw)

    for t in data.get("transitions", []):
        cat = t.get("category", "")
        transitions.append(UIStateTransition(
            trigger=f"카테고리 '{cat}' 클릭",
            from_state=t.get("from_state", ""),
            to_state=t.get("to_state", ""),
            key_finding=t.get("key_finding", ""),
        ))

    # 공통 패턴으로 나머지 카테고리도 추론
    pattern = data.get("common_pattern", "")
    if pattern:
        for cat in CATEGORIES[3:]:
            transitions.append(UIStateTransition(
                trigger=f"카테고리 '{cat}' 클릭",
                from_state="이전 카테고리 또는 초기 상태",
                to_state=f"{cat} 제품 목록 표시 (공통 패턴 적용)",
                key_finding=pattern,
            ))

    return transitions


# ── Phase 3: 스크롤 탐색 ─────────────────────────────────────────────

async def phase3_scroll(page: Page, client: openai.OpenAI) -> list[ScrollArea]:
    """스크롤 가능 영역 탐색 — 세로/가로 모두"""
    print("  [Phase 3] 스크롤 탐색...")
    scroll_areas: list[ScrollArea] = []

    # 3-1. 제품 목록 세로 스크롤 (카테고리 선택 상태 전제)
    before_b64 = await _screenshot_b64(page)
    product_scroll = await page.evaluate(_JS_SCROLL_CHECK, "")

    # 페이지 메인 스크롤 (move → wheel)
    await page.mouse.move(640, 500)
    await page.mouse.wheel(0, 600)
    await page.wait_for_timeout(800)
    after_b64_scroll1 = await _screenshot_b64(page)

    # 위로 복귀
    await page.mouse.move(640, 500)
    await page.mouse.wheel(0, -600)
    await page.wait_for_timeout(500)

    # 3-2. 오른쪽 패널 스크롤 가능 여부
    right_scroll = await page.evaluate("""() => {
        const candidates = [
            '#pcBuildWrap', '.side_build', '[class*="build_wrap"]',
            '[class*="estimate_wrap"]', '[class*="right"]'
        ];
        for (const sel of candidates) {
            const el = document.querySelector(sel);
            if (el) {
                const s = window.getComputedStyle(el);
                const isScrollable = el.scrollHeight > el.clientHeight + 10;
                const r = el.getBoundingClientRect();
                return {
                    selector: sel,
                    scrollable: isScrollable,
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    bbox: {x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)},
                    cls: el.className.slice(0, 60),
                };
            }
        }
        return {selector: null, scrollable: false};
    }""")

    after_b64_right = None
    if right_scroll.get("scrollable") and right_scroll.get("bbox"):
        bx, by = right_scroll["bbox"]["x"], right_scroll["bbox"]["y"]
        await page.mouse.move(bx, by)
        await page.mouse.wheel(0, 400)
        await page.wait_for_timeout(800)
        after_b64_right = await _screenshot_b64(page)
        await page.mouse.move(bx, by)
        await page.mouse.wheel(0, -400)
        await page.wait_for_timeout(500)

    # 3-3. LLM 분석
    system = """\
다나와 PC견적 페이지의 스크롤 동작을 분석합니다.
before/after 스크린샷을 비교하여 스크롤 영역 정보를 JSON으로 출력하세요.

출력 형식:
{
  "scroll_areas": [
    {
      "name": "영역명",
      "location": "가운데/오른쪽/왼쪽",
      "axis": "세로/가로",
      "what_appears": "스크롤 시 새로 나타나는 내용 설명"
    }
  ]
}"""

    user_content = [
        _text_msg(f"페이지 세로 스크롤 (스크롤 가능 높이: {product_scroll.get('scrollHeight', '?')}px):"),
        _img_msg(before_b64),
        _text_msg("↓ 600px 아래로 스크롤 후"),
        _img_msg(after_b64_scroll1),
    ]

    if after_b64_right:
        user_content += [
            _text_msg(f"오른쪽 패널 스크롤 ({right_scroll.get('selector', '')}, "
                      f"스크롤 가능: {right_scroll.get('scrollable')}):"),
            _img_msg(after_b64_right),
        ]
    else:
        user_content.append(_text_msg(
            f"오른쪽 패널 스크롤 불가 또는 영역 미발견 "
            f"(selector: {right_scroll.get('selector')}, "
            f"scrollable: {right_scroll.get('scrollable')})"
        ))

    raw = _llm_call(client, system, user_content, max_tokens=600)
    data = _parse_json(raw)

    for s in data.get("scroll_areas", []):
        scroll_areas.append(ScrollArea(
            name=s.get("name", ""),
            location=s.get("location", ""),
            axis=s.get("axis", "세로"),
            what_appears=s.get("what_appears", ""),
        ))
        print(f"    ✓ 스크롤 영역: {s.get('name','')} ({s.get('axis','')}) — {s.get('what_appears','')[:50]}")

    if not scroll_areas:
        print("    ⚠ 스크롤 영역 분석 결과 없음")

    return scroll_areas


# ── Phase 4: 인터랙션 탐색 ───────────────────────────────────────────

_JS_DO_SEARCH = """
(query) => {
    const inputs = Array.from(document.querySelectorAll('input[type="text"]'));
    const searchInput = inputs.find(inp => {
        const placeholder = inp.placeholder || '';
        const name = inp.name || '';
        return placeholder.includes('검색') || name.includes('search') ||
               inp.closest('[class*="search"]');
    }) || inputs[0];
    if (!searchInput) return {success: false, inputs: inputs.length};
    searchInput.value = query;
    searchInput.dispatchEvent(new Event('input', {bubbles: true}));
    searchInput.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', keyCode: 13, bubbles: true}));
    return {success: true, selector: searchInput.outerHTML.slice(0, 100)};
}
"""


async def phase4_interaction(page: Page, client: openai.OpenAI) -> list[str]:
    """검색 + 결과 구조 탐색 → 발견 사실 반환"""
    print("  [Phase 4] 인터랙션 탐색 (검색)...")
    facts: list[str] = []

    before_b64 = await _screenshot_b64(page)
    search_result = await page.evaluate(_JS_DO_SEARCH, "i3-12100")
    await page.wait_for_timeout(2000)
    after_b64 = await _screenshot_b64(page)

    after_dom = await page.evaluate("""() => ({
        products: document.querySelectorAll('tr[class*="productList"]').length,
        ad: document.querySelectorAll('tr.recom_area').length,
        add_btns: document.querySelectorAll('.btn_choice2.wishAction').length,
        sort_btns: document.querySelectorAll('[class*="sort"] a, [onclick*="sort"]').length,
    })""")

    system = """\
다나와 PC견적 페이지에서 검색 후 결과를 분석합니다.
before/after 스크린샷과 DOM 변화를 보고 발견된 사실 목록을 JSON으로 출력하세요.

출력 형식:
{
  "facts": [
    "검색 결과 구조에 대한 발견 사실 1",
    "발견 사실 2",
    ...
  ],
  "search_result_layout": "검색 결과 화면 레이아웃 설명"
}"""

    raw = _llm_call(client, system, [
        _text_msg(f"검색어 'i3-12100' 입력 (성공: {search_result.get('success')})"),
        _img_msg(before_b64),
        _text_msg(f"↓ 검색 후 (제품: {after_dom['products']}개, 광고: {after_dom['ad']}개, "
                  f"담기버튼: {after_dom['add_btns']}개, 정렬버튼: {after_dom['sort_btns']}개)"),
        _img_msg(after_b64),
    ], max_tokens=600)

    data = _parse_json(raw)
    facts = data.get("facts", [])

    # DOM 수치 기반 자동 사실 추가
    if after_dom["products"] > 0:
        facts.append(f"'i3-12100' 검색 시 제품 {after_dom['products']}개 (광고 {after_dom['ad']}개 포함)")
    if after_dom["add_btns"] > 0:
        facts.append(f"검색 결과에서 .btn_choice2.wishAction 버튼 {after_dom['add_btns']}개 확인됨")

    for f in facts[:3]:
        print(f"    → {f[:70]}")

    return facts


# ── 최종 합성 ─────────────────────────────────────────────────────────

async def explore_ui(page: Page, client: openai.OpenAI, model: str = MODEL) -> DanawaKnowledge:
    """
    4단계 능동 탐색 실행 → DanawaKnowledge 반환
    BASE_KNOWLEDGE와 병합하여 검증된 사실 보존.
    """
    print("\n  === Active UI Explorer 시작 ===")

    overview = await phase1_overview(page, client)
    transitions = await phase2_categories(page, client)
    scroll_areas = await phase3_scroll(page, client)
    discovered_facts = await phase4_interaction(page, client)

    # BASE_KNOWLEDGE에 탐색 결과 병합
    from knowledge import _merge
    discovered = DanawaKnowledge(
        url=overview.get("_dom", {}).get("url", ""),
        regions=[
            UIRegion(
                name=r.get("name", ""),
                location=r.get("location", ""),
                description=r.get("description", ""),
            )
            for r in overview.get("regions", [])
            if r.get("name")
        ],
        workflow=[],
        quirks=[],
        discovered_facts=discovered_facts,
        state_transitions=transitions,
        scroll_areas=scroll_areas,
    )

    merged = _merge(BASE_KNOWLEDGE, discovered)
    print(f"\n  === 탐색 완료 ===")
    print(f"  상태 전이: {len(merged.state_transitions)}개")
    print(f"  스크롤 영역: {len(merged.scroll_areas)}개")
    print(f"  발견 사실: {len(merged.discovered_facts)}개")
    return merged


# ── CLI ──────────────────────────────────────────────────────────────

async def _run(phases: list[int] | None = None, save: bool = True):
    api_key = os.environ.get("LETSUR_API_KEY")
    if not api_key:
        raise RuntimeError("LETSUR_API_KEY 없음")

    client = openai.OpenAI(base_url=LETSUR_BASE_URL, api_key=api_key)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--window-size=1280,900"])
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()

        print(f"[UI Explorer] 다나와 로드 중...")
        await page.goto(DANAWA_ESTIMATE_URL, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)

        knowledge = await explore_ui(page, client)
        await browser.close()

    print("\n" + "=" * 60)
    print(knowledge.to_context())
    print("=" * 60)

    if save:
        save_knowledge(knowledge)
        print(f"\n✓ 저장: {CACHE_PATH}")

    return knowledge


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="다나와 능동 UI 탐색기")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()
    asyncio.run(_run(save=not args.no_save))
