"""
main_bu.py — browser-use 기반 다나와 PC 견적 에이전트 (v2)

기존 main.py 대비 변경점:
- browser-use 라이브러리가 DOM 인터랙션, 루프감지, 플래닝을 담당
- 다나와 전용 JS 툴(sort_cheapest, add_product 등)을 custom action으로 등록
- 좌표 클릭 실패 / LLM second-guess 문제 해소

사용법:
  .venv/bin/python main_bu.py --task office_50
  .venv/bin/python main_bu.py --task gaming_100
  .venv/bin/python main_bu.py --task budget_30
"""

import asyncio
import argparse
import os

from dotenv import load_dotenv
from browser_use import Agent, Tools
from browser_use.llm import ChatOpenAI
from browser_use.agent.views import ActionResult
from browser_use.browser.session import BrowserSession

from tasks import TASKS_BY_ID
from tools_bu import (
    tool_select_category,
    tool_search,
    tool_sort_cheapest,
    tool_get_products,
    tool_add_product,
    tool_filter,
    tool_clear_filters,
    tool_get_cart,
    tool_remove_part,
)

load_dotenv()

DANAWA_ESTIMATE_URL = (
    "https://shop.danawa.com/virtualestimate/"
    "?controller=estimateMain&methods=index&marketPlaceSeq=16"
)

# 다나와 페이지 작업 지침 (시스템 프롬프트에 추가)
_DANAWA_SYSTEM_EXT = """
## 다나와 PC 견적 페이지 커스텀 툴

이 페이지에서는 아래 커스텀 툴을 반드시 활용하세요.
표준 클릭/입력 대신 이 툴이 훨씬 신뢰성 높습니다.

### 필수 워크플로우 (부품 1개 선택)
1. danawa_select_category("메모리")   ← 카테고리 선택
2. danawa_search("DDR4 8G")           ← 검색창 입력
3. danawa_sort_cheapest()             ← 낮은 가격순 정렬
4. danawa_get_products()              ← 목록 확인 (이름·가격)
5. danawa_add_product(1)              ← 담기 (담기 버튼은 JS만 작동 — 좌표 클릭 불가!)
→ danawa_add_product 성공 → 즉시 다음 부품으로 넘어갈 것

### 주의사항
- 담기 버튼은 반드시 danawa_add_product() 사용 — 좌표 클릭으로는 절대 안 됨
- 검색창 입력은 danawa_search() 사용 — TYPE 액션 대신
- 정렬은 danawa_sort_cheapest() 사용
- 검색 후 카테고리 탭 팝업이 뜨면 자동 처리됨 (추가 클릭 불필요)
- 광고 제품(상단 2~3개)은 건너뛰고 그 아래 제품 선택
- 부품 선택 시 사무용은 브랜드/규격으로 검색 (예: "DDR4 8G", "NVMe 256", "i3-12100")
"""


def _make_tools() -> Tools:
    """다나와 전용 custom action 등록"""
    tools = Tools()

    @tools.action("다나와: 부품 카테고리 선택. category 예시: CPU, 메인보드, 메모리, SSD, 케이스, 파워")
    async def danawa_select_category(category: str, browser_session: BrowserSession) -> ActionResult:
        page = await browser_session.get_current_page()
        result = await tool_select_category(page, category)
        return ActionResult(extracted_content=result)

    @tools.action("다나와: 검색창(#searchProduct)에 검색어 입력 + 검색버튼 클릭. TYPE 액션 대신 이것 사용")
    async def danawa_search(query: str, browser_session: BrowserSession) -> ActionResult:
        page = await browser_session.get_current_page()
        result = await tool_search(page, query)
        return ActionResult(extracted_content=result)

    @tools.action("다나와: 낮은 가격순 정렬. 정렬 버튼 클릭 대신 이것 사용")
    async def danawa_sort_cheapest(browser_session: BrowserSession) -> ActionResult:
        page = await browser_session.get_current_page()
        result = await tool_sort_cheapest(page)
        return ActionResult(extracted_content=result)

    @tools.action("다나와: 현재 제품 목록 텍스트 반환 (광고 제외, 이름+가격). 담기 전에 목록 확인용")
    async def danawa_get_products(browser_session: BrowserSession) -> ActionResult:
        page = await browser_session.get_current_page()
        result = await tool_get_products(page)
        return ActionResult(extracted_content=result)

    @tools.action(
        "다나와: N번째 제품 담기 버튼 클릭. "
        "담기 버튼은 JS 이벤트라 좌표 클릭 불가 — 반드시 이 툴 사용. "
        "성공 시 제품명·가격 반환"
    )
    async def danawa_add_product(n: int, browser_session: BrowserSession) -> ActionResult:
        page = await browser_session.get_current_page()
        result = await tool_add_product(page, n)
        return ActionResult(extracted_content=result)

    @tools.action("다나와: 필터 체크박스 클릭. label 예시: 'DDR4', '인텔', 'AMD', '신품', 'NVMe'")
    async def danawa_filter(label: str, browser_session: BrowserSession) -> ActionResult:
        page = await browser_session.get_current_page()
        result = await tool_filter(page, label)
        return ActionResult(extracted_content=result)

    @tools.action("다나와: 현재 카테고리 필터 전체 해제")
    async def danawa_clear_filters(browser_session: BrowserSession) -> ActionResult:
        page = await browser_session.get_current_page()
        result = await tool_clear_filters(page)
        return ActionResult(extracted_content=result)

    @tools.action("다나와: 현재 견적 카트(오른쪽 패널) 현황 확인")
    async def danawa_get_cart(browser_session: BrowserSession) -> ActionResult:
        page = await browser_session.get_current_page()
        result = await tool_get_cart(page)
        return ActionResult(extracted_content=result)

    @tools.action("다나와: 견적에서 부품 삭제. category 예시: CPU, 메인보드, 메모리, SSD")
    async def danawa_remove_part(category: str, browser_session: BrowserSession) -> ActionResult:
        page = await browser_session.get_current_page()
        result = await tool_remove_part(page, category)
        return ActionResult(extracted_content=result)

    return tools


async def run_task(task_id: str, headless: bool = False, use_tools: bool = True, use_context: bool = True):
    api_key = os.environ.get("LETSUR_API_KEY")
    if not api_key:
        raise RuntimeError("LETSUR_API_KEY 환경변수가 없습니다. .env 파일을 확인하세요.")

    task = TASKS_BY_ID[task_id]

    llm = ChatOpenAI(
        model="gemini-3-flash-preview",  # type: ignore[arg-type]
        api_key=api_key,
        base_url="https://gateway.letsur.ai/v1",
        temperature=0,
    )

    browser_session = BrowserSession(
        headless=headless,
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    )

    mode_label = (
        "툴O + 구조설명O" if (use_tools and use_context) else
        "툴O + 구조설명X" if (use_tools and not use_context) else
        "툴X + 구조설명X"
    )

    agent = Agent(
        task=task.description,
        llm=llm,
        tools=_make_tools() if use_tools else None,
        browser_session=browser_session,
        use_vision=True,
        extend_system_message=_DANAWA_SYSTEM_EXT if (use_tools and use_context) else None,
        max_actions_per_step=3,
        loop_detection_enabled=True,
        initial_actions=[{"navigate": {"url": DANAWA_ESTIMATE_URL}}],
    )

    print(f"\n{'='*60}")
    print(f"[browser-use] 태스크: {task_id}  |  모드: {mode_label}")
    print(f"{'='*60}\n")

    history = await agent.run()

    print(f"\n{'='*60}")
    print(f"[최종 결과] ({mode_label})")
    print(history.final_result())
    print(f"총 스텝 수: {len(history.history)}")
    print(f"{'='*60}")


async def main():
    parser = argparse.ArgumentParser(description="weg-agent v2 (browser-use 기반)")
    parser.add_argument("--task", default="office_50", choices=list(TASKS_BY_ID.keys()))
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-tools", action="store_true", help="커스텀 툴 없이 browser-use 기본 액션만 사용")
    parser.add_argument("--no-context", action="store_true", help="툴은 주되 페이지 구조 설명 없이 실행")
    args = parser.parse_args()

    await run_task(
        args.task,
        headless=args.headless,
        use_tools=not args.no_tools,
        use_context=not args.no_context,
    )


if __name__ == "__main__":
    asyncio.run(main())
