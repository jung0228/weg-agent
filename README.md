# weg-agent

다나와에서 예산에 맞는 PC 견적을 자동으로 찾아주는 웹 에이전트.
**Planner-Executor + AgentBrain + WALT-style Tools + Pure Vision**

---

## 전체 구조

```
태스크 (예산 + 목적)
    │
    ▼
[agent.py] 오케스트레이터
    │
    ├─ 1. [planner.py] 계획 수립 (LLM 1회 호출)
    │       태스크 → 서브태스크 목록 ["CPU 선택", "RAM 선택", ...]
    │
    ├─ 2. [executor.py] × N단계 반복
    │       각 서브태스크를 AgentBrain 미니 ReAct로 실행
    │       │
    │       ├─ [som.py] perceive(page)
    │       │    스크린샷만 캡처 (DOM 수집 없음)
    │       │    → ScreenState(screenshot_b64, url, w, h)
    │       │
    │       ├─ LLM Vision (AgentBrain 출력)
    │       │    Eval:    이전 액션 결과 평가 (Success/Failed/N/A)
    │       │    Memory:  이 스텝에서 기억할 정보
    │       │    Predict: 다음 액션 실행 시 예상 결과
    │       │    Goal:    다음 액션 의도 한 줄
    │       │    Action:  TOOL ... / CLICK (x,y) / DONE ...
    │       │
    │       ├─ [tools.py] TOOL 명령 → DOM 직접 실행 (신뢰성↑)
    │       │    select_category / search / sort_cheapest
    │       │    get_products / add_product (광고 자동 스킵)
    │       │
    │       └─ [actions.py] 좌표 기반 Playwright 실행
    │
    ├─ 3. [memory.py] WorkingMemory 업데이트
    │       선택 부품 + 잔여 예산 → 다음 Executor에 주입
    │
    ├─ 4. Executor 실패 시 → [planner.py] replan()
    │       남은 단계만 재수립
    │
    └─ 5. [eval.py] LLM-as-Judge 평가 (선택)
             results/<task_id>_<timestamp>.json 저장
```

---

## 버전 히스토리

| | v1 | v2 | v3 (현재) |
|---|---|---|---|
| **구조** | 단일 flat ReAct | Planner → Executor × N | 동일 + WALT Tools |
| **인식** | SoM (DOM + 스크린샷 오버레이) | Adaptive SoM (text-first) | 순수 Vision (스크린샷만) |
| **액션** | `CLICK [N]` DOM ID | `CLICK [N]` DOM ID | `TOOL ...` / `CLICK (x,y)` 좌표 |
| **담기 문제** | filter_for_goal에서 제외→실패 | 동일 | DOM .click()으로 직접 해결 |
| **광고 스킵** | 없음 | 없음 | `recom_area` 자동 필터링 |
| **LLM 출력** | `Thought/Action` 2줄 | `Eval/Memory/Goal/Action` 4줄 | + `Predict:` 5줄 |

---

## 파일별 역할

### `tools.py` — WALT 스타일 Danawa 전용 Tool (v3 신규)

DOM을 직접 조작하는 고수준 액션 모음. LLM이 좌표를 추론할 필요 없음.

```
TOOL select_category "CPU"   → JS: 카테고리 텍스트 매칭 → .click()
TOOL search "i3-12100"       → JS: 검색창 value 세팅 → Enter
TOOL sort_cheapest           → JS: "낮은 가격순" 텍스트 매칭 → .click()
TOOL get_products            → JS: tr[class*="productList_"] 수집, recom_area 제외
                                   → 제품명/가격 텍스트 목록 반환
TOOL add_product 1           → JS: .btn_choice2.wishAction 수집, recom_area 제외
                                   → n번째 .click() (광고 자동 스킵)
```

**왜 DOM 직접 클릭인가?**
브라우저 분석 결과, "담기" 버튼(`<a class="btn_choice2 wishAction">`)은
jQuery 이벤트 리스너가 등록된 `<a>` 태그. `element.click()` / `dispatchEvent`로
정상 작동 확인. 좌표 추론 없이 100% 신뢰성.

---

### `som.py` — 순수 Vision 인식 (v3 단순화)

```python
async def perceive(page) -> ScreenState:
    screenshot_b64 = await page.screenshot()
    return ScreenState(screenshot_b64, title, url, width, height)
```

DOM 수집/오버레이 완전 제거. LLM이 스크린샷만 보고 판단.

---

### `executor.py` — 미니 ReAct + AgentBrain (v3: Predict 추가)

Browser Use의 `AgentBrain` 패턴 + Predict 필드 추가:

```
Eval:    Success
Memory:  i3-12100 검색 완료, 낮은 가격순 정렬됨
Predict: 1번째 제품이 담기고 오른쪽 패널에 추가될 것
Goal:    첫 번째 비광고 제품 담기
Action:  TOOL add_product 1
```

**Predict 필드 효과**: 액션 전 예상 결과를 명시 → 이상한 예측이면
LLM이 스스로 다른 액션 선택 → hallucination 감소.

권장 워크플로우 (부품 하나 추가, 6스텝):
```
1. TOOL select_category "CPU"
2. TOOL search "i3-12100"
3. TOOL sort_cheapest
4. TOOL get_products          ← 목록 보고 n 결정
5. TOOL add_product 1
6. DONE "... | 부품:CPU | 이름:... | 가격:..."
```

---

### `actions.py` — 액션 파싱

```
TOOL name [args]          → DOM 기반 고수준 액션 (tools.py 위임)
CLICK (x, y)              → Playwright mouse.click(x, y)
TYPE_ENTER (x, y) "text"  → click + keyboard.type + Enter
SCROLL DOWN / UP          → mouse.wheel
GOTO https://...          → page.goto
WAIT                      → wait_for_timeout(2000)
DONE "요약 | 부품:X | 이름:Y | 가격:Z"
```

---

### `memory.py` — 워킹 메모리

```python
WorkingMemory:
    total_budget: int
    selected_parts: dict[str, PartInfo]   # {"CPU": PartInfo(name, price)}
    completed_steps: list[str]
    scratchpad: str

    .spent          # 지출 합계
    .remaining      # 잔여 예산
    .to_context()   # Executor 시스템 프롬프트에 주입
```

---

### `planner.py` — 계획 수립

LLM 1회 호출로 태스크 → 서브태스크 리스트 변환.
`replan()`: 실패 시 남은 단계를 현재 메모리 컨텍스트와 함께 재수립.

---

### `agent.py` — 오케스트레이터

```python
WebAgent.run(task, page):
    1. 예산 추출
    2. create_plan() → steps 리스트
    3. for step in steps:
         result = executor.run(step, page, memory)
         if not result.success: steps = replan(...)
    4. _compile_answer(memory) → 최종 출력
```

---

## 기술 출처

| 기술 | 출처 | 적용 |
|------|------|------|
| **Planner-Executor 분리** | Go-Browse (ApGa, 2024) | `planner.py` + `executor.py` |
| **Replanner (실패 복구)** | Go-Browse | `agent.py` replan() |
| **WALT Tool 추상화** | WALT (Salesforce AI, 2024) | `tools.py` 전체 |
| **Hybrid deterministic+agentic** | WALT | TOOL + CLICK 혼용 |
| **광고 자동 스킵** | WALT (Tool이 노이즈 처리) | `add_product` recom_area 필터 |
| **AgentBrain 4-field** | Browser Use | `Eval/Memory/Goal/Action` |
| **Predict 필드** | weg-agent 자체 확장 | 액션 전 예측으로 hallucination↓ |
| **순수 Vision** | OpenAI CUA / Claude Computer Use 트렌드 | `som.py` 단순화 |

---

## 설치 및 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# .env에 LETSUR_API_KEY 입력 (ASCII만)

# 특정 태스크 (평가 없이)
python main.py --task office_50 --no-eval

# 전체 실행
python main.py

# headless 모드
python main.py --headless
```

---

## 테스트 케이스

| ID | 예산 | 목적 | 필수 부품 |
|----|------|------|----------|
| `office_50` | 50만원 | 사무용 | CPU + 메인보드 + RAM 8GB↑ + SSD 256GB↑ |
| `gaming_100` | 100만원 | 게이밍 | 위 + GPU (RTX 4060 급) |
| `budget_30` | 30만원 | 최저가 | CPU(내장그래픽) + RAM 8GB + SSD 128GB↑ |

---

## 알려진 버그

### 버튼 좌표 클릭 실패 (반복 패턴)
```
[4] vision | CLICK (959, 587) → X 버튼 클릭 시도
[5] vision | Failed | CLICK (959, 587) → 같은 좌표 재시도
[6] vision | Failed | CLICK (959, 567) → 좌표 약간 이동해도 실패
```
**원인**: 오른쪽 패널의 X(삭제) 버튼은 `담기` 버튼과 동일한 구조 — 좌표 클릭이 아닌 DOM 직접 조작 필요.
픽셀이 정확히 버튼 위가 아닌 옆/밖을 찍는 경우가 많음. 특히 작은 X 버튼(~20px)은 좌표 오차 허용 범위가 거의 없음.

**해결**: `TOOL remove_part "메인보드"` 추가 — JS로 카테고리명 매칭 후 삭제 버튼 DOM `.click()`.
좌표 추론 없이 100% 신뢰성 보장.

**패턴 일반화**: Danawa의 모든 인터랙션(담기/삭제/정렬/검색)을 TOOL로 처리.
좌표 클릭은 TOOL로 처리 못하는 예외 상황에서만 사용.

---

## 남은 개선 방향

### 단기
- **Replanner 횟수 제한**: 현재 무한 replan 가능 → 최대 2회로 제한
- **X 버튼 JS 셀렉터 강화**: `_JS_REMOVE_PART`에서 다나와 실제 클래스명 확인 후 정확도 향상
- **TOOL select_category 셀렉터 정확도**: 오른쪽 패널 항목과 왼쪽 필터를 혼동하는 경우 수정

### 중기
- **Go-Browse 상태 그래프**: Danawa UI를 DAG로 모델링 → 현재 어느 페이지인지 추적, 엉뚱한 스크롤/탐색 방지
- **trajectory 수집 → few-shot**: `results/*.json` 성공 사례를 다음 실행 few-shot으로 주입

### 장기
- **Tool 자동 발견**: WALT처럼 새 사이트 진입 시 Tool을 자동 탐색·생성
- **작은 버튼 hit-area 보정**: X처럼 작은 버튼은 좌표 기반으로 클릭할 때 ±10px 보정 로직
