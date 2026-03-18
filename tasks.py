"""
tasks.py — 다나와 PC 견적 태스크 정의
테스트 케이스 3개 포함.
"""
from dataclasses import dataclass


# 다나와 PC 견적 툴 (카테고리별 부품 추가 페이지)
DANAWA_ESTIMATE_URL = (
    "https://shop.danawa.com/virtualestimate/"
    "?controller=estimateMain&methods=index&marketPlaceSeq=16"
)


@dataclass
class Task:
    id: str
    description: str          # 에이전트에게 줄 태스크 문자열
    budget: int               # 예산 (원)
    purpose: str              # 사무용 / 게이밍 / 최저가
    start_url: str = DANAWA_ESTIMATE_URL

    def prompt(self) -> str:
        return self.description


# ── 공통 페이지 설명 (에이전트가 페이지 구조를 이해하도록) ──────────────

_PAGE_CONTEXT = """
현재 페이지는 다나와 PC 견적 툴이다. 조작 방법:
1. 왼쪽 부품 목록에서 원하는 카테고리(CPU, 메인보드, RAM, SSD 등) 옆 "선택" 버튼 클릭
2. 열리는 검색 화면에서 가격순 정렬 후 예산에 맞는 제품 클릭하여 선택
3. 검색 시 "사무용" 같은 용도어 대신 브랜드/모델명 사용 (예: "라이젠5", "i3-12100", "DDR4 8GB")
4. 부품 선택이 완료되면 왼쪽 목록에 해당 부품이 추가됨
"""


# ── 테스트 케이스 3개 ─────────────────────────────────────

TASKS = [
    Task(
        id="office_50",
        description=(
            f"{_PAGE_CONTEXT}\n"
            "태스크: 예산 50만원으로 사무용 PC를 조합해줘.\n"
            "필수 부품: CPU, 메인보드, RAM(8GB 이상), SSD(256GB 이상).\n"
            "GPU는 내장그래픽으로 충분 (별도 GPU 불필요).\n"
            "각 카테고리 버튼을 클릭해서 부품을 검색하고, 가격순 정렬 후 예산 내 제품을 찾아.\n"
            "최종적으로 선택한 부품 목록(모델명 + 가격)과 합산 총액을 DONE으로 알려줘."
        ),
        budget=500_000,
        purpose="사무용",
    ),
    Task(
        id="gaming_100",
        description=(
            f"{_PAGE_CONTEXT}\n"
            "태스크: 예산 100만원으로 게이밍 PC를 조합해줘.\n"
            "필수 부품: CPU, 메인보드, RAM(16GB 이상), SSD(512GB 이상), GPU(필수).\n"
            "GPU에 예산의 30~40%를 배분하는 게 좋아. RTX 4060 또는 RX 7600 수준 목표.\n"
            "각 카테고리 버튼을 클릭해서 부품을 검색하고, 가격순 정렬 후 예산 내 제품을 찾아.\n"
            "최종적으로 선택한 부품 목록(모델명 + 가격)과 합산 총액을 DONE으로 알려줘."
        ),
        budget=1_000_000,
        purpose="게이밍",
    ),
    Task(
        id="budget_30",
        description=(
            f"{_PAGE_CONTEXT}\n"
            "태스크: 예산 30만원으로 최저가 PC를 조합해줘.\n"
            "인터넷, 유튜브, 문서작업 정도면 충분해. 이전 세대 CPU(인텔 10세대, AMD 라이젠 3000)도 OK.\n"
            "필수 부품: CPU(내장그래픽 포함), RAM(8GB), SSD(128GB 이상).\n"
            "각 카테고리 버튼을 클릭해서 부품을 검색하고, 가격순 정렬 후 예산 내 최저가 제품을 찾아.\n"
            "최종적으로 선택한 부품 목록(모델명 + 가격)과 합산 총액을 DONE으로 알려줘."
        ),
        budget=300_000,
        purpose="최저가",
    ),
]

TASKS_BY_ID = {t.id: t for t in TASKS}
