"""
agent.py — Planner-Executor 오케스트레이터 (동적 플래닝)
1. Planner: 초기 계획 수립 (1회)
2. Executor: 각 서브태스크를 AgentBrain 기반 미니 ReAct로 실행
3. WorkingMemory: 선택 부품 + 잔여 예산을 구조화해 Executor에 주입
4. review_plan: 매 스텝 후 결과를 보고 남은 계획 동적 조정
"""
import os
import re
from dataclasses import dataclass, field

import openai
from playwright.async_api import Page

from memory import WorkingMemory
from planner import create_plan, review_plan, PlanStep
from executor import Executor, ExecStep
from knowledge import load_knowledge, DanawaKnowledge


MODEL = "gemini-3-flash-preview"
LETSUR_BASE_URL = "https://gateway.letsur.ai/v1"
MAX_TOTAL_PLAN_STEPS = 12  # 전체 플랜 스텝 상한 (무한루프 방지)

DANAWA_ESTIMATE_URL = (
    "https://shop.danawa.com/virtualestimate/"
    "?controller=estimateMain&methods=index&marketPlaceSeq=16"
)


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

    async def run(self, task: str, page: Page, enforce_budget: bool = True) -> AgentResult:
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

        # ── 3. 단계별 실행 (동적 플래닝) ─────────────────────────
        executor = Executor(self.client, MODEL, knowledge=knowledge)
        all_exec_steps: list[ExecStep] = []

        i = 0
        total_plan_steps_run = 0
        while i < len(steps):
            # 전체 스텝 상한 — 무한루프 방지
            if total_plan_steps_run >= MAX_TOTAL_PLAN_STEPS:
                print(f"\n[안전 종료] 최대 {MAX_TOTAL_PLAN_STEPS}단계 도달 — 조기 종료")
                break

            plan_step = steps[i]
            goal = _build_goal(plan_step, enforce_budget=enforce_budget)
            total_plan_steps_run += 1
            print(f"\n[Step {total_plan_steps_run} | Plan {i+1}/{len(steps)}] {goal}")
            print("-" * 50)

            # 매 스텝 시작 전 다나와 estimate 페이지 복구
            if "virtualestimate" not in page.url:
                print("  [복구] 다나와 estimate 페이지로 이동 중...")
                try:
                    await page.goto(
                        DANAWA_ESTIMATE_URL,
                        wait_until="domcontentloaded",
                        timeout=20000,
                    )
                    await page.wait_for_timeout(1500)
                except Exception as _nav_e:
                    print(f"  [복구 실패] {_nav_e}")

            step_result = await executor.run(goal, page, memory)
            all_exec_steps.extend(step_result.steps)
            summary = step_result.summary

            if step_result.success:
                memory.completed_steps.append(f"{plan_step.name} → {summary[:60]}")
                print(f"  ✓ 완료: {summary[:80]}")
            else:
                print(f"  ✗ 실패: {summary}")

            # ── 동적 플래닝: 매 스텝 후 남은 계획 리뷰 ──────────
            remaining = steps[i+1:]
            if remaining:
                print(f"  [Planner 리뷰] 남은 {len(remaining)}단계 조정 중...")
                updated_remaining = review_plan(
                    task=task,
                    budget=budget,
                    spent_so_far=memory.spent,
                    completed=memory.completed_steps,
                    last_step_name=plan_step.name,
                    last_step_result=summary,
                    last_step_success=step_result.success,
                    remaining_steps=remaining,
                    client=self.client,
                    model=MODEL,
                )
                steps = steps[:i+1] + updated_remaining

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


def _build_goal(step: PlanStep, enforce_budget: bool = True) -> str:
    """PlanStep → executor에 전달할 goal 문자열 생성."""
    parts = [step.name]
    if step.budget and enforce_budget:
        parts.append(f"최대 {step.budget:,}원 이내로 선택")
    elif not enforce_budget:
        parts.append("단계별 예산 제한 없음 — 가장 저렴한 제품 선택")
    if step.hint:
        # hint는 필터/규격 참고 정보 (강제 검색어 아님)
        # 카테고리+필터 방식(방법 A)으로 자율 탐색, hint는 필터 선택의 참고용
        parts.append(f"요구사항: {step.hint} (카테고리+필터 방식으로 조건에 맞는 가장 저렴한 제품 선택)")
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
