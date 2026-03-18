"""
knowledge.py — 다나와 UI 팩추얼 지식 모듈
Web-CogReasoner 논문 기반: Factual Knowledge tier

구조:
  UIElement   — 단일 요소 (버튼/입력창 등)
  UIRegion    — 영역 (오른쪽 패널, 가운데 목록 등)
  DanawaKnowledge — 전체 페이지 지식 (정적 base + 동적 discovered)

흐름:
  1. 하드코딩된 base 지식 (검증된 사실) 로드
  2. ui_explorer가 LLM으로 탐색한 지식을 merge
  3. executor 시스템 프롬프트에 to_context()로 주입
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


CACHE_PATH = Path("knowledge/danawa_ui.json")


# ── 데이터 구조 ──────────────────────────────────────────────────────

@dataclass
class UIElement:
    name: str          # 논리 이름 (예: "담기 버튼")
    selector: str      # CSS selector (예: ".btn_choice2.wishAction")
    description: str   # 기능 설명
    verified: bool = False  # DOM 분석으로 직접 확인된 사실


@dataclass
class UIRegion:
    name: str          # 영역명 (예: "PC 주요구성 패널")
    location: str      # 위치 힌트 (예: "오른쪽", "가운데")
    description: str   # 역할
    elements: list[UIElement] = field(default_factory=list)


@dataclass
class UIStateTransition:
    """클릭/스크롤 후 UI가 어떻게 변하는지 기록"""
    trigger: str          # 트리거 액션 (예: "카테고리 'CPU' 클릭")
    from_state: str       # 이전 상태 (예: "카테고리 미선택, 가운데 빈 화면")
    to_state: str         # 이후 상태 (예: "CPU 제품 목록 23개 표시, 광고 2개 상단")
    key_finding: str      # 핵심 발견 (예: "검색창이 가운데 상단에 새로 나타남")


@dataclass
class ScrollArea:
    """스크롤 가능한 영역 정보"""
    name: str             # 영역명 (예: "제품 목록")
    location: str         # 위치 (예: "가운데")
    axis: str             # "세로" or "가로"
    what_appears: str     # 스크롤 시 나타나는 내용


@dataclass
class DanawaKnowledge:
    url: str = ""
    regions: list[UIRegion] = field(default_factory=list)
    workflow: list[str] = field(default_factory=list)
    quirks: list[str] = field(default_factory=list)
    discovered_facts: list[str] = field(default_factory=list)
    # 능동 탐색으로 발견된 상태 전이 정보
    state_transitions: list[UIStateTransition] = field(default_factory=list)
    scroll_areas: list[ScrollArea] = field(default_factory=list)

    def to_context(self) -> str:
        """executor 시스템 프롬프트에 주입할 텍스트 블록"""
        lines = ["## 다나와 PC견적 UI 팩추얼 지식 (Factual Knowledge)"]

        lines.append("\n### 페이지 영역 구조")
        for r in self.regions:
            lines.append(f"**{r.name}** ({r.location}): {r.description}")
            for el in r.elements:
                mark = "✓" if el.verified else "~"
                lines.append(f"  {mark} {el.name}: `{el.selector}` — {el.description}")

        if self.state_transitions:
            lines.append("\n### 클릭/액션 시 상태 전이 (State Transitions)")
            for t in self.state_transitions:
                lines.append(f"  [{t.trigger}]")
                lines.append(f"    Before: {t.from_state}")
                lines.append(f"    After:  {t.to_state}")
                if t.key_finding:
                    lines.append(f"    ★ {t.key_finding}")

        if self.scroll_areas:
            lines.append("\n### 스크롤 영역 (Scroll Areas)")
            for s in self.scroll_areas:
                lines.append(f"  {s.name} ({s.location}, {s.axis}): {s.what_appears}")

        if self.workflow:
            lines.append("\n### 부품 추가 워크플로우")
            for i, step in enumerate(self.workflow, 1):
                lines.append(f"  {i}. {step}")

        if self.quirks:
            lines.append("\n### 알려진 UI 특이사항")
            for q in self.quirks:
                lines.append(f"  ⚠ {q}")

        if self.discovered_facts:
            lines.append("\n### 탐색으로 발견된 사실")
            for f in self.discovered_facts:
                lines.append(f"  → {f}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "regions": [
                {
                    "name": r.name,
                    "location": r.location,
                    "description": r.description,
                    "elements": [
                        {
                            "name": e.name,
                            "selector": e.selector,
                            "description": e.description,
                            "verified": e.verified,
                        }
                        for e in r.elements
                    ],
                }
                for r in self.regions
            ],
            "workflow": self.workflow,
            "quirks": self.quirks,
            "discovered_facts": self.discovered_facts,
            "state_transitions": [
                {
                    "trigger": t.trigger,
                    "from_state": t.from_state,
                    "to_state": t.to_state,
                    "key_finding": t.key_finding,
                }
                for t in self.state_transitions
            ],
            "scroll_areas": [
                {
                    "name": s.name,
                    "location": s.location,
                    "axis": s.axis,
                    "what_appears": s.what_appears,
                }
                for s in self.scroll_areas
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DanawaKnowledge":
        regions = []
        for r in d.get("regions", []):
            elements = [
                UIElement(
                    name=e["name"],
                    selector=e["selector"],
                    description=e["description"],
                    verified=e.get("verified", False),
                )
                for e in r.get("elements", [])
            ]
            regions.append(UIRegion(
                name=r["name"],
                location=r["location"],
                description=r["description"],
                elements=elements,
            ))
        state_transitions = [
            UIStateTransition(
                trigger=t["trigger"],
                from_state=t["from_state"],
                to_state=t["to_state"],
                key_finding=t.get("key_finding", ""),
            )
            for t in d.get("state_transitions", [])
        ]
        scroll_areas = [
            ScrollArea(
                name=s["name"],
                location=s["location"],
                axis=s.get("axis", "세로"),
                what_appears=s["what_appears"],
            )
            for s in d.get("scroll_areas", [])
        ]
        return cls(
            url=d.get("url", ""),
            regions=regions,
            workflow=d.get("workflow", []),
            quirks=d.get("quirks", []),
            discovered_facts=d.get("discovered_facts", []),
            state_transitions=state_transitions,
            scroll_areas=scroll_areas,
        )


# ── 정적 기본 지식 (DOM 분석으로 검증된 사실) ────────────────────────

BASE_KNOWLEDGE = DanawaKnowledge(
    url="https://prod.danawa.com/info/?pcode=...",
    regions=[
        UIRegion(
            name="PC 주요구성 패널",
            location="오른쪽",
            description="카테고리 선택 버튼 + 현재 담긴 부품 목록 표시",
            elements=[
                UIElement(
                    "카테고리 버튼",
                    "a[onclick*='selectCategory'], .build_category a",
                    "클릭 시 가운데 영역에 해당 카테고리 제품 표시",
                    verified=False,
                ),
                UIElement(
                    "담긴 부품 행",
                    ".choice_item, tr[id*='choice']",
                    "현재 견적에 추가된 부품 목록",
                    verified=False,
                ),
                UIElement(
                    "부품 삭제 버튼",
                    "[class*='del'], [class*='remove']",
                    "담긴 부품 삭제 — 반드시 TOOL remove_part 사용 (좌표 클릭 실패)",
                    verified=True,
                ),
            ],
        ),
        UIRegion(
            name="제품 목록 영역",
            location="가운데",
            description="선택 카테고리 제품 검색·필터·목록 표시",
            elements=[
                UIElement(
                    "제품 행 (비광고)",
                    "tr[class*='productList_']:not(.recom_area)",
                    "실제 제품 데이터 행 (TOOL get_products가 자동 수집)",
                    verified=True,
                ),
                UIElement(
                    "광고/추천 제품 행",
                    "tr.recom_area",
                    "상단 광고 제품 — TOOL이 자동 필터링하므로 신경 쓸 필요 없음",
                    verified=True,
                ),
                UIElement(
                    "담기 버튼",
                    ".btn_choice2.wishAction",
                    "jQuery 이벤트 기반 — DOM .click()만 작동, 좌표 클릭 금지",
                    verified=True,
                ),
                UIElement(
                    "정렬 버튼",
                    "a[onclick*='sort'], .sort_item a",
                    "낮은가격순 정렬 — TOOL sort_cheapest 사용",
                    verified=False,
                ),
            ],
        ),
    ],
    workflow=[
        "TOOL select_category \"CPU\"   ← 오른쪽 패널에서 카테고리 선택",
        "TOOL search \"Celeron G6900\"   ← 검색창에 모델명 입력 + 엔터",
        "TOOL sort_cheapest             ← 낮은 가격순 정렬",
        "TOOL get_products              ← 비광고 제품 목록 확인 (n 결정용)",
        "TOOL add_product N             ← n번째 비광고 제품 담기",
        "DONE \"... | 부품:X | 이름:Y | 가격:Z\"",
    ],
    quirks=[
        "담기 버튼(.btn_choice2.wishAction)은 jQuery 리스너 — Playwright 좌표 클릭 실패, JS .click()만 동작",
        "광고 제품(tr.recom_area)은 목록 상단 2~3개 — TOOL이 자동 제외하므로 번호 그대로 사용 가능",
        "X(삭제) 버튼도 작아서(~20px) 좌표 클릭 실패 — TOOL remove_part \"카테고리\" 사용",
        "검색 후 제품이 안 나오면 모델명 단순화 (브랜드 제거, 규격만 입력)",
    ],
)


# ── 저장/로드 ──────────────────────────────────────────────────────

def save_knowledge(knowledge: DanawaKnowledge, path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(knowledge.to_dict(), f, ensure_ascii=False, indent=2)


def load_knowledge(path: Path = CACHE_PATH) -> DanawaKnowledge:
    """캐시된 지식 로드. 없으면 BASE_KNOWLEDGE 반환."""
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return DanawaKnowledge.from_dict(json.load(f))
    return BASE_KNOWLEDGE


def _merge(base: DanawaKnowledge, discovered: DanawaKnowledge) -> DanawaKnowledge:
    """
    BASE_KNOWLEDGE (검증된 사실 우선) + LLM 탐색 결과 병합.
    - 영역: base 영역 유지, discovered에 새 영역만 추가
    - 워크플로우: base 우선
    - state_transitions / scroll_areas: discovered 것 추가 (base에 없음)
    - quirks / discovered_facts: 합치기 (중복 제거)
    """
    base_region_names = {r.name for r in base.regions}
    merged_regions = list(base.regions)
    for r in discovered.regions:
        if r.name not in base_region_names:
            merged_regions.append(r)

    workflow = base.workflow if base.workflow else discovered.workflow

    seen_quirks = set(base.quirks)
    quirks = list(base.quirks)
    for q in discovered.quirks:
        if q not in seen_quirks:
            quirks.append(q)
            seen_quirks.add(q)

    # state_transitions, scroll_areas는 discovered에서만 올 수 있음 (base에 없음)
    return DanawaKnowledge(
        url=discovered.url or base.url,
        regions=merged_regions,
        workflow=workflow,
        quirks=quirks,
        discovered_facts=discovered.discovered_facts,
        state_transitions=base.state_transitions + discovered.state_transitions,
        scroll_areas=base.scroll_areas + discovered.scroll_areas,
    )
