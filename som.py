"""
som.py — 순수 비전 기반 화면 인식
DOM 수집 없이 스크린샷만 캡처해서 LLM에게 전달한다.
LLM이 스크린샷을 보고 픽셀 좌표를 직접 추론한다.
"""
import base64
from dataclasses import dataclass

from playwright.async_api import Page


@dataclass
class ScreenState:
    screenshot_b64: str   # base64 PNG
    page_title: str
    page_url: str
    width: int            # 뷰포트 픽셀 너비
    height: int           # 뷰포트 픽셀 높이


async def perceive(page: Page) -> ScreenState:
    """
    현재 페이지의 스크린샷을 찍어 ScreenState로 반환한다.
    DOM 수집/오버레이 없음 — LLM이 픽셀 좌표를 직접 추론한다.
    """
    vp = page.viewport_size or {"width": 1280, "height": 800}
    width, height = vp["width"], vp["height"]

    raw_bytes = await page.screenshot(full_page=False)
    screenshot_b64 = base64.standard_b64encode(raw_bytes).decode()

    return ScreenState(
        screenshot_b64=screenshot_b64,
        page_title=await page.title(),
        page_url=page.url,
        width=width,
        height=height,
    )
