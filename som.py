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

    try:
        raw_bytes = await page.screenshot(full_page=False, timeout=30000)
    except Exception:
        # 페이지가 로딩 중이거나 응답 없음 → 잠시 기다렸다가 재시도
        await page.wait_for_timeout(3000)
        try:
            raw_bytes = await page.screenshot(full_page=False, timeout=20000)
        except Exception:
            # 최후 수단: 빈 흰 이미지 반환 (에이전트가 WAIT 액션 선택하도록)
            import io
            from PIL import Image as _Img
            img = _Img.new("RGB", (width, height), color=(255, 255, 255))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            raw_bytes = buf.getvalue()
    screenshot_b64 = base64.standard_b64encode(raw_bytes).decode()

    return ScreenState(
        screenshot_b64=screenshot_b64,
        page_title=await page.title(),
        page_url=page.url,
        width=width,
        height=height,
    )
