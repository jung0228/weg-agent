"""
ui_explorer.py — LLM 기반 UI 팩추얼 지식 탐색기
Web-CogReasoner 논문의 Factual Knowledge 수집 단계 구현

흐름:
  1. 페이지 스크린샷 캡처 (Vision 입력)
  2. 핵심 DOM 샘플 추출 (선택자/클래스명/요소 수 — 경량)
  3. LLM이 스크린샷 + DOM 샘플 분석 → 구조화된 UI 지식 출력
  4. BASE_KNOWLEDGE와 병합 (검증된 사실은 base 우선)
  5. knowledge/danawa_ui.json 캐싱 → 이후 실행에서 재사용

사용:
  python ui_explorer.py              # 탐색 실행 + 결과 출력
  python ui_explorer.py --no-cache   # 캐시 무시하고 재탐색
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path

import openai
from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page

from knowledge import (
    BASE_KNOWLEDGE, DanawaKnowledge, UIElement, UIRegion,
    CACHE_PATH, save_knowledge, load_knowledge,
)

load_dotenv()

DANAWA_ESTIMATE_URL = "https://prod.danawa.com/info/?pcode=22166839"
MODEL = "gemini-3-flash-preview"
LETSUR_BASE_URL = "https://gateway.letsur.ai/v1"

# ── DOM 샘플러 ────────────────────────────────────────────────────────

_JS_DOM_SAMPLE = """
() => {
    const safe = (el) => el ? el.outerHTML.slice(0, 120) : null;
    const count = (sel) => document.querySelectorAll(sel).length;
    const classOf = (sel) => {
        const el = document.querySelector(sel);
        return el ? el.className.slice(0, 80) : null;
    };
    const textOf = (sel) => {
        const el = document.querySelector(sel);
        return el ? el.textContent.trim().slice(0, 60) : null;
    };

    return {
        // 오른쪽 패널 후보들
        right_panel_candidates: [
            '#pcBuildWrap', '.side_build', '[class*="build_wrap"]',
            '[class*="estimate"]', '[class*="wish"]'
        ].map(sel => ({sel, found: count(sel), cls: classOf(sel)})),

        // 카테고리 버튼
        category_buttons: count('[class*="category"] a, [class*="cate"] a'),
        category_sample: safe(document.querySelector('[class*="category"] a')),

        // 제품 목록
        product_rows_all: count('tr[class*="productList"]'),
        product_rows_ad: count('tr.recom_area'),
        product_row_sample: safe(document.querySelector('tr[class*="productList"]:not(.recom_area)')),

        // 담기 버튼
        add_btns_total: count('.btn_choice2, [class*="wish"], [class*="choice"]'),
        add_btn_wishAction: count('.btn_choice2.wishAction'),
        add_btn_sample: safe(document.querySelector('.btn_choice2.wishAction')),

        // 검색창
        search_inputs: count('input[type="text"], input[name*="search"]'),
        search_sample: safe(document.querySelector('input[type="text"]')),

        // 삭제 버튼
        del_btns: count('[class*="del"], [class*="remove"], [class*="close"]'),
        del_sample: safe(document.querySelector('[class*="del_btn"], [class*="choice_del"]')),

        // 정렬
        sort_links: count('[class*="sort"] a, [onclick*="sort"]'),
        sort_sample: safe(document.querySelector('[class*="sort"] a')),

        // 현재 URL + 타이틀
        url: location.href,
        title: document.title.slice(0, 60),
        viewport: {w: window.innerWidth, h: window.innerHeight},
    };
}
"""

# ── LLM 프롬프트 ────────────────────────────────────────────────────

_EXPLORE_SYSTEM = """\
당신은 웹 UI 분석 전문가입니다.
다나와 PC견적 페이지의 스크린샷과 DOM 샘플을 분석하여
에이전트가 활용할 수 있는 구조화된 팩추얼 지식을 추출하세요.

## 출력 형식 (JSON만, 마크다운 없이)
{
  "regions": [
    {
      "name": "영역 이름",
      "location": "위치 (오른쪽/가운데/왼쪽/상단/하단)",
      "description": "이 영역의 역할",
      "elements": [
        {
          "name": "요소 이름",
          "selector": "CSS selector (구체적일수록 좋음)",
          "description": "기능과 주의사항"
        }
      ]
    }
  ],
  "workflow": ["단계1", "단계2", ...],
  "quirks": ["특이사항1", "특이사항2", ...],
  "discovered_facts": ["새로 발견한 사실1", ...]
}

## 주의
- DOM 샘플에서 실제 클래스명/선택자를 최대한 정확하게 추출
- 이미 알고 있는 사실(담기 버튼 = .btn_choice2.wishAction 등)도 재확인
- 스크린샷에서 보이는 UI 영역 위치를 설명에 포함
"""


# ── 탐색기 핵심 ─────────────────────────────────────────────────────

async def explore_ui(page: Page, client: openai.OpenAI, model: str) -> DanawaKnowledge:
    """
    페이지를 탐색하고 팩추얼 지식을 추출한다.
    BASE_KNOWLEDGE와 병합 후 반환.
    """
    print("  [Explorer] 스크린샷 캡처 중...")
    raw_bytes = await page.screenshot(full_page=False)
    screenshot_b64 = base64.standard_b64encode(raw_bytes).decode()

    print("  [Explorer] DOM 샘플 추출 중...")
    try:
        dom_sample = await page.evaluate(_JS_DOM_SAMPLE)
    except Exception as e:
        dom_sample = {"error": str(e)}

    dom_text = json.dumps(dom_sample, ensure_ascii=False, indent=2)

    print("  [Explorer] LLM 분석 중...")
    user_content = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"},
        },
        {
            "type": "text",
            "text": f"## DOM 샘플\n```json\n{dom_text}\n```\n\n위 스크린샷과 DOM 샘플을 분석하여 UI 구조를 JSON으로 출력하세요.",
        },
    ]

    response = client.chat.completions.create(
        model=model,
        max_tokens=1500,
        messages=[
            {"role": "system", "content": _EXPLORE_SYSTEM},
            {"role": "user", "content": user_content},
        ],
    )
    raw = response.choices[0].message.content.strip()

    # JSON 파싱
    discovered = _parse_knowledge(raw, dom_sample)

    # BASE_KNOWLEDGE와 병합
    merged = _merge(BASE_KNOWLEDGE, discovered)
    return merged


def _parse_knowledge(raw: str, dom_sample: dict) -> DanawaKnowledge:
    """LLM 출력 → DanawaKnowledge 파싱"""
    import re
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    try:
        data = json.loads(cleaned)
    except Exception:
        # JSON 블록 추출 시도
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = {}
        else:
            data = {}

    regions = []
    for r in data.get("regions", []):
        elements = [
            UIElement(
                name=e.get("name", ""),
                selector=e.get("selector", ""),
                description=e.get("description", ""),
                verified=False,  # LLM이 발견한 것 → 미검증
            )
            for e in r.get("elements", [])
            if e.get("name") and e.get("selector")
        ]
        if r.get("name"):
            regions.append(UIRegion(
                name=r["name"],
                location=r.get("location", ""),
                description=r.get("description", ""),
                elements=elements,
            ))

    # DOM 샘플에서 직접 검증된 사실 자동 추가
    auto_facts = _auto_facts_from_dom(dom_sample)

    return DanawaKnowledge(
        url=dom_sample.get("url", ""),
        regions=regions,
        workflow=data.get("workflow", []),
        quirks=data.get("quirks", []),
        discovered_facts=data.get("discovered_facts", []) + auto_facts,
    )


def _auto_facts_from_dom(dom: dict) -> list[str]:
    """DOM 샘플에서 자동으로 추출 가능한 사실 목록"""
    facts = []
    ad = dom.get("product_rows_ad", 0)
    total = dom.get("product_rows_all", 0)
    wish = dom.get("add_btn_wishAction", 0)

    if total > 0:
        facts.append(f"현재 제품 목록 행: 총 {total}개 (광고 {ad}개, 비광고 {total - ad}개)")
    if wish > 0:
        facts.append(f".btn_choice2.wishAction 버튼 {wish}개 확인 (담기 버튼 셀렉터 검증됨)")
    elif dom.get("add_btns_total", 0) > 0:
        facts.append(f"담기 관련 버튼 {dom['add_btns_total']}개 — .wishAction은 0개 (카테고리 미선택 상태일 수 있음)")

    # 오른쪽 패널 후보 확인
    for candidate in dom.get("right_panel_candidates", []):
        if candidate.get("found", 0) > 0:
            facts.append(f"오른쪽 패널 셀렉터 후보: `{candidate['sel']}` (found={candidate['found']})")
            break

    return facts


def _merge(base: DanawaKnowledge, discovered: DanawaKnowledge) -> DanawaKnowledge:
    """
    BASE_KNOWLEDGE (검증된 사실) + LLM 발견 지식 병합.
    같은 이름의 영역이 있으면 base 요소를 우선하고 discovered 요소를 추가.
    """
    # 영역 병합
    base_region_names = {r.name for r in base.regions}
    merged_regions = list(base.regions)  # base 영역 먼저
    for r in discovered.regions:
        if r.name not in base_region_names:
            merged_regions.append(r)  # 새 영역만 추가

    # 워크플로우: base 우선, discovered에 새 내용 있으면 병합
    workflow = base.workflow if base.workflow else discovered.workflow

    # 특이사항: 합치기 (중복 제거)
    seen = set(base.quirks)
    quirks = list(base.quirks)
    for q in discovered.quirks:
        if q not in seen:
            quirks.append(q)
            seen.add(q)

    return DanawaKnowledge(
        url=discovered.url or base.url,
        regions=merged_regions,
        workflow=workflow,
        quirks=quirks,
        discovered_facts=discovered.discovered_facts,
    )


# ── CLI 진입점 ───────────────────────────────────────────────────────

async def _run_explore(no_cache: bool = False, save: bool = True):
    api_key = os.environ.get("LETSUR_API_KEY")
    if not api_key:
        raise RuntimeError("LETSUR_API_KEY 환경변수 없음")

    client = openai.OpenAI(base_url=LETSUR_BASE_URL, api_key=api_key)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--window-size=1280,900"])
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        print(f"\n[UI Explorer] 다나와 PC견적 페이지 로드 중...")
        await page.goto(DANAWA_ESTIMATE_URL, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)  # 동적 콘텐츠 로드 대기

        print(f"[UI Explorer] 탐색 시작...\n")
        knowledge = await explore_ui(page, client, MODEL)

        await browser.close()

    # 결과 출력
    print("\n" + "="*60)
    print("[UI Explorer] 탐색 결과")
    print("="*60)
    print(knowledge.to_context())

    if save:
        save_knowledge(knowledge)
        print(f"\n✓ 저장됨: {CACHE_PATH}")

    return knowledge


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="다나와 UI 탐색기")
    parser.add_argument("--no-cache", action="store_true", help="캐시 무시하고 재탐색")
    parser.add_argument("--no-save", action="store_true", help="캐시 저장 안 함")
    args = parser.parse_args()

    asyncio.run(_run_explore(no_cache=args.no_cache, save=not args.no_save))
