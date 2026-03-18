"""
agent.py — Planner-Executor 오케스트레이터
1. Planner: 태스크를 서브태스크 목록으로 1회 분해
2. Executor: 각 서브태스크를 AgentBrain 기반 미니 ReAct로 실행
3. WorkingMemory: 선택 부품 + 잔여 예산을 구조화해 Executor에 주입
4. Replan: Executor 실패 시 남은 단계 재수립
"""
import os
import re
from dataclasses import dataclass, field

import openai
from playwright.async_api import Page

from memory import WorkingMemory
from planner import create_plan, replan, PlanStep
from executor import Executor, ExecStep
from knowledge import load_knowledge, DanawaKnowledge


MODEL = "gemini-3-flash-preview"
LETSUR_BASE_URL = "https://gateway.letsur.ai/v1"


@dataclass
class Step:
    """eval.py / main.py 와의 하위 호환을 위해 유지"""
    step: int
    thought: str
    action_raw: str
    action: object
    observation: str
    screenshot_b64: str


@dataclass
class AgentResult:
    task: str
    steps: list[Step] = field(default_factory=list)
    final_answer: str = ""
    success: bool = False


class WebAgent:
    def __init__(self, api_key: str | None = None, explore_ui: bool = False):
        self.client = openai.OpenAI(
            base_url=LETSUR_BASE_URL,
            api_key=api_key or os.environ["LETSUR_API_KEY"],
        )
        self.explore_ui = explore_ui

    async def run(self, task: str, page: Page) -> AgentResult:
        result = AgentResult(task=task)

        print(f"\n{'='*60}")
        print(f"태스크: {task[:80]}...")
        print(f"{'='*60}")

        # ── 0. UI 팩추얼 지식 로드 (또는 탐색) ────────────────────
        knowledge = await self._load_or_explore_knowledge(page)
        print(f"[Knowledge] {len(knowledge.regions)}개 영역, "
              f"{sum(len(r.elements) for r in knowledge.regions)}개 요소 로드됨")

        # ── 1. 예산 추출 ─────────────────────────────────────────
        budget = _extract_budget(task)
        memory = WorkingMemory(total_budget=budget)
        print(f"\n[예산] {budget:,}원\n")

        # ── 2. 계획 수립 (1회 LLM) ───────────────────────────────
        print("[Planner] 계획 수립 중...")
        steps: list[PlanStep] = create_plan(task, budget, self.client, MODEL)
        print(f"[Planner] {len(steps)}단계 계획:")
        for i, s in enumerate(steps, 1):
            budget_str = f"  (최대 {s.budget:,}원)" if s.budget else ""
            hint_str = f"  → {s.hint}" if s.hint else ""
            print(f"  {i}. {s.name}{budget_str}{hint_str}")

        # ── 3. 단계별 실행 ────────────────────────────────────────
        executor = Executor(self.client, MODEL, knowledge=knowledge)
        all_exec_steps: list[ExecStep] = []

        i = 0
        while i < len(steps):
            plan_step = steps[i]
            goal = _build_goal(plan_step)
            print(f"\n[Step {i+1}/{len(steps)}] {goal}")
            print("-" * 50)

            step_result = await executor.run(goal, page, memory)
            all_exec_steps.extend(step_result.steps)
            summary = step_result.summary

            if step_result.success:
                memory.completed_steps.append(f"{plan_step.name} → {summary[:60]}")
                print(f"  ✓ 완료: {summary[:80]}")
            else:
                print(f"  ✗ 실패: {summary}")
                remaining_original = steps[i+1:]
                if remaining_original:
                    print(f"  [Replanner] 남은 {len(remaining_original)}단계 재수립 중...")
                    new_remaining = replan(
                        task=task,
                        budget=budget,
                        completed=memory.completed_steps,
                        failed_step=plan_step.name,
                        memory_context=memory.to_context(),
                        client=self.client,
                        model=MODEL,
                    )
                    steps = steps[:i+1] + new_remaining
                    print(f"  [Replanner] {len(new_remaining)}단계로 재수립")

            i += 1

        # ── 4. 최종 답변 컴파일 ──────────────────────────────────
        final_answer = _compile_answer(memory)
        result.final_answer = final_answer
        result.success = bool(memory.selected_parts)

        # Step 리스트 변환 (eval.py 호환)
        flat_counter = 0
        for es in all_exec_steps:
            flat_counter += 1
            result.steps.append(Step(
                step=flat_counter,
                thought=f"[{es.eval_prev}] Goal={es.goal_intent}",
                action_raw=es.action_raw,
                action=es.action,
                observation=es.observation,
                screenshot_b64=es.screenshot_b64,
            ))

        print(f"\n{'='*60}")
        print(f"[완료]\n{final_answer}")
        print(f"{'='*60}")

        return result


# ── 헬퍼 ──────────────────────────────────────────────────────────

async def _noop(*args, **kwargs):
    pass


# ── WebAgent 내부 헬퍼 (인스턴스 메서드) ─────────────────────────────

# monkey-patch 방식 대신 agent 클래스 안에 메서드 추가를 위해 클래스 밖에서 정의
async def _load_or_explore_impl(self, page: Page) -> DanawaKnowledge:
    """
    UI 지식 로드 전략:
    1. explore_ui=True → ui_explorer로 실시간 탐색 + 캐시 저장
    2. 캐시 파일 있음 → 캐시에서 로드
    3. 없음 → BASE_KNOWLEDGE 사용
    """
    if self.explore_ui:
        from ui_explorer import explore_ui as _explore
        from knowledge import save_knowledge, CACHE_PATH
        print("[Knowledge] UI 탐색 모드 — 페이지 분석 중...")
        knowledge = await _explore(page, self.client, MODEL)
        save_knowledge(knowledge)
        print(f"[Knowledge] 탐색 완료, 캐시 저장: {CACHE_PATH}")
        return knowledge
    else:
        from knowledge import load_knowledge
        return load_knowledge()


# WebAgent에 메서드 주입
WebAgent._load_or_explore_knowledge = _load_or_explore_impl  # type: ignore


def _build_goal(step: PlanStep) -> str:
    """PlanStep → executor에 전달할 goal 문자열 생성."""
    parts = [step.name]
    if step.budget:
        parts.append(f"최대 {step.budget:,}원 이내로 선택")
    if step.hint:
        parts.append(f"추천 검색어: {step.hint}")
    return " — ".join(parts)


def _extract_budget(task: str) -> int:
    """태스크 텍스트에서 예산 숫자 추출 (원 단위)"""
    m = re.search(r"(\d+)만\s*원", task)
    if m:
        return int(m.group(1)) * 10_000
    m = re.search(r"([\d,]+)\s*원", task)
    if m:
        return int(m.group(1).replace(",", ""))
    return 0


def _compile_answer(memory: WorkingMemory) -> str:
    """WorkingMemory에서 최종 답변 문자열을 생성한다."""
    lines = ["## 최종 PC 견적"]
    if memory.selected_parts:
        for cat, p in memory.selected_parts.items():
            lines.append(f"- {cat}: {p.name}  ({p.price:,}원)")
        lines.append(f"\n총액: {memory.spent:,}원  /  예산: {memory.total_budget:,}원")
        if memory.total_budget > 0:
            ratio = memory.spent / memory.total_budget * 100
            lines.append(f"예산 사용률: {ratio:.1f}%")
    else:
        lines.append("(부품 선택 정보 없음)")
        if memory.completed_steps:
            lines.append("\n## 실행 기록")
            for s in memory.completed_steps:
                lines.append(f"- {s}")
    return "\n".join(lines)
