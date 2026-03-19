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
        """executor 시스템 프롬프트에 주입할 텍스트 블록 (Bloom's 3-tier)"""
        lines = ["## 다나와 PC견적 UI 지식"]

        # ── Factual: 물리적 UI 요소 ──────────────────────────────
        lines.append("\n### [Factual] 페이지 영역 구조")
        for r in self.regions:
            lines.append(f"**{r.name}** ({r.location}): {r.description}")
            for el in r.elements:
                mark = "✓" if el.verified else "~"
                lines.append(f"  {mark} {el.name}: {el.description}")

        if self.state_transitions:
            lines.append("\n### [Factual] 액션 → 상태 전이")
            for t in self.state_transitions:
                lines.append(f"  [{t.trigger}] → {t.to_state}")
                if t.key_finding:
                    lines.append(f"    ★ {t.key_finding}")

        if self.scroll_areas:
            lines.append("\n### [Factual] 스크롤 영역")
            for s in self.scroll_areas:
                lines.append(f"  {s.name} ({s.location}): {s.what_appears}")

        # ── Conceptual: 요소 간 관계·역할 ────────────────────────
        if self.workflow:
            lines.append("\n### [Conceptual] 페이지 흐름 이해")
            for i, step in enumerate(self.workflow, 1):
                lines.append(f"  {i}. {step}")

        # ── Procedural: 목표 달성 행동 절차 ─────────────────────
        if self.quirks:
            lines.append("\n### [Procedural] 부품 선택 절차 & 주의사항")
            for q in self.quirks:
                lines.append(f"  ⚠ {q}")

        if self.discovered_facts:
            lines.append("\n### [Procedural] 탐색으로 확인된 사실")
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
    url="https://shop.danawa.com/virtualestimate/?controller=estimateMain&methods=index&marketPlaceSeq=16",
    regions=[
        UIRegion(
            name="PC 주요구성 패널 (카테고리 선택)",
            location="오른쪽 사이드바 (x≈1050~1280, 세로 스크롤 필요)",
            description="CPU·메인보드·RAM·SSD 등 부품 카테고리 버튼 목록. 버튼 클릭 → 가운데 제품 목록 열림. 부품 담기 완료 시 버튼 아래 제품명 표시됨.",
            elements=[
                UIElement(
                    "카테고리 버튼",
                    "a.pd_item_title (텍스트: CPU, 메인보드, 메모리, SSD, 케이스, 파워 등)",
                    "클릭하면 가운데 영역에 해당 카테고리 제품 검색창+목록이 열림",
                    verified=True,
                ),
                UIElement(
                    "담긴 부품 표시",
                    "카테고리 버튼 아래 제품명 텍스트",
                    "이미 선택된 부품은 버튼 아래 제품명으로 표시됨",
                    verified=True,
                ),
            ],
        ),
        UIRegion(
            name="제품 검색·목록 영역",
            location="가운데 (x≈50~1000)",
            description="카테고리 선택 후 열리는 제품 목록. 상단에 검색창(#searchProduct)과 필터, 아래에 제품 행 목록. 상단 2~3개는 광고 제품.",
            elements=[
                UIElement(
                    "검색창",
                    "#searchProduct (placeholder: '상품명을 검색하세요.')",
                    "CSS 셀렉터로 정확히 특정 가능 → TYPE_CSS \"#searchProduct\" \"검색어\" 로 사용 권장. 좌표 추론 대신 이 방법 사용",
                    verified=True,
                ),
                UIElement(
                    "낮은 가격순 정렬 버튼",
                    "텍스트 '낮은 가격순' 탭/버튼",
                    "클릭하면 제품 목록이 가격 오름차순으로 재정렬됨. **한 번만 클릭하면 충분, 반복 클릭 금지**",
                    verified=True,
                ),
                UIElement(
                    "제품 행",
                    "tr 행 (제품명·가격 텍스트 포함)",
                    "실제 제품 데이터. 상단 2~3개는 광고이므로 그 아래 제품 클릭 권장",
                    verified=True,
                ),
                UIElement(
                    "담기 버튼",
                    "각 제품 행 오른쪽 '담기' 또는 '선택' 버튼",
                    "클릭하면 해당 부품이 견적에 담김. 좌표 클릭이 실패하면 제품 행 텍스트 영역을 클릭",
                    verified=True,
                ),
            ],
        ),
    ],
    # [Conceptual] 페이지 흐름
    workflow=[
        "오른쪽 패널에서 원하는 카테고리(CPU, 메인보드 등) 버튼을 클릭",
        "TYPE_CSS \"#searchProduct\" \"검색어\" → 제품 검색 (좌표 추론 불필요)",
        "TOOL sort_cheapest → 낮은 가격순 정렬",
        "TOOL get_products → 제품 목록 확인 (이름·가격 텍스트로 확인)",
        "TOOL add_product 1 → 첫 번째 제품 담기 (담기 버튼은 JS만 작동 — 좌표 클릭 불가)",
        "DONE \"목표완료 | 부품:카테고리명 | 이름:제품명 | 가격:숫자\" 로 완료 보고",
    ],
    # [Procedural] 절차 규칙 (quirks 필드 재사용)
    quirks=[
        "제품 검색은 TYPE_CSS \"#searchProduct\" \"검색어\" 사용 — 좌표 추론 없이 검색창 직접 입력 (TYPE_ENTER 좌표 추론 대신)",
        "정렬 완료 후 제품이 스크린샷에 보이면 즉시 클릭 — 정렬 재클릭·검색 재시도 금지",
        "같은 TYPE_ENTER 좌표가 2회 연속 실패하면 TYPE_CSS 로 전환, 그래도 안 되면 스크롤+시각탐색",
        "광고 제품(상단 2~3개)은 가격이 비싼 경우 많으므로 건너뛰고 그 아래 제품 선택",
        "필터 체크박스는 왼쪽 사이드바에 있음 — 제조사(AMD/Intel), 내장그래픽 유무 등",
        "담기 버튼 좌표 클릭이 실패하면 제품명이나 제품 행 다른 영역 클릭 시도",
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
