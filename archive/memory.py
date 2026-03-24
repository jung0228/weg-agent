"""
memory.py — 에이전트 워킹 메모리
Browser Use의 AgentBrain 패턴 참고:
  evaluation_previous_goal / memory / next_goal 구조로
  매 스텝이 명시적으로 이전 결과를 평가하고 다음 목표를 설정한다.
"""
import re
from dataclasses import dataclass, field


@dataclass
class PartInfo:
    category: str    # "CPU", "메인보드", "RAM", ...
    name: str
    price: int       # 원


@dataclass
class WorkingMemory:
    """플래너-익스큐터 전체에 걸쳐 유지되는 상태"""
    total_budget: int = 0
    selected_parts: dict[str, PartInfo] = field(default_factory=dict)
    completed_steps: list[str] = field(default_factory=list)   # "단계명 → 요약"
    scratchpad: str = ""   # 익스큐터가 자유롭게 기록하는 메모

    @property
    def spent(self) -> int:
        return sum(p.price for p in self.selected_parts.values())

    @property
    def remaining(self) -> int:
        return self.total_budget - self.spent

    def add_part(self, category: str, name: str, price: int):
        self.selected_parts[category] = PartInfo(category=category, name=name, price=price)

    def to_context(self) -> str:
        """익스큐터 시스템 프롬프트에 주입할 현재 상태 텍스트"""
        lines = [
            "## 현재 견적 상태",
            f"총 예산: {self.total_budget:,}원  |  사용: {self.spent:,}원  |  잔여: {self.remaining:,}원",
        ]
        if self.selected_parts:
            lines.append("선택된 부품:")
            for cat, p in self.selected_parts.items():
                lines.append(f"  - {cat}: {p.name}  ({p.price:,}원)")
        if self.completed_steps:
            lines.append("완료된 단계:")
            for s in self.completed_steps:
                lines.append(f"  ✓ {s}")
        if self.scratchpad:
            lines.append(f"메모: {self.scratchpad}")
        return "\n".join(lines)


def try_parse_part(done_msg: str) -> tuple[str, str, int] | None:
    """
    DONE 메시지에서 부품 정보를 추출 시도.
    익스큐터가 아래 형식으로 출력하도록 지시됨:
      DONE "CPU 선택 완료 | 부품:CPU | 이름:Intel Core i5-13400F | 가격:189000"
    반환: (category, name, price) or None
    """
    cat = re.search(r'부품:([^|"]+)', done_msg)
    name = re.search(r'이름:([^|"]+)', done_msg)
    price = re.search(r'가격:(\d[\d,]*)', done_msg)
    if cat and name and price:
        return (
            cat.group(1).strip(),
            name.group(1).strip(),
            int(price.group(1).replace(",", "")),
        )
    return None
