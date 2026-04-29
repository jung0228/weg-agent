# Web Transition Memory Research Plan

작성일: 2026-04-28

## 0. 한 줄 요약

지금 웹 에이전트 연구는 `무엇을 해야 하는가`를 기억하고 추상화하는 쪽으로 많이 발전했다. 다음 병목은 `이 행동을 하면 화면이 어떻게 바뀌는가`다. 이 노트의 가설은 단순하다.

> 웹 월드 모델을 파라미터 안에 굽는 대신, 실제 웹 탐색에서 관찰한 `(현재 관찰, 행동, 다음 변화)`를 메모리화하고, 이를 검색해서 행동 후보별 다음 상태를 예측하자.

즉 우리의 방향은 `memory as world model`이다. 정확히는 `O_t + A_i => O^*_{t+1}` 형태의 transition memory를 저장하고, 새 웹 태스크에서 행동 후보를 고를 때 이 메모리를 불러와 "이 버튼을 누르면 무엇이 일어날 가능성이 높은가"를 추론한다.

## 1. 문제 재정의

### 기존 연구가 많이 푼 것

`Synapse`, `AWM`, `ReasoningBank`, `SkillRL`은 모두 raw trajectory를 그대로 쓰는 것이 약하다는 데 동의한다. 그래서 각각 다른 추상화 단위를 만든다.

| 계열 | 저장 단위 | 잘하는 것 | 아직 약한 것 |
|---|---|---|---|
| Synapse | full trajectory exemplar | long-horizon 예시 제공 | 사이트별 세부 실행이 섞임 |
| AWM | reusable workflow | 반복 sub-routine 추출 | 현재 UI stage와 action outcome 검증이 약함 |
| ReasoningBank | reasoning item | 성공/실패에서 transferable lesson 추출 | UI 전이 자체는 모델링하지 않음 |
| SkillRL | skill bank | skill 사용법을 SFT/RL로 policy에 주입 | 웹 UI 변화 예측보다는 전략/스킬 중심 |

### 아직 남은 핵심 병목

웹에서는 같은 목표라도 UI 구조가 다르다. 더 중요한 것은 행동 결과가 불확실하다는 점이다.

- 카테고리를 누르면 product list로 이동할 수도 있고, dropdown만 열릴 수도 있다.
- `Select` 버튼은 checkout으로 갈 수도 있고, 로그인 modal을 띄울 수도 있다.
- 필터를 클릭하면 URL이 바뀔 수도 있고, DOM 일부만 비동기로 바뀔 수도 있다.
- `more` 버튼은 "더 많은 게시글"일 수도 있고 "댓글 더 보기"일 수도 있다.

따라서 다음 연구 질문은 이렇게 잡는 것이 좋다.

> Can a web agent use interaction memory to predict and verify the UI transition caused by each candidate action?

## 2. Ours: Transition-Aware Memory for Web Agents

### 핵심 차이

World model 계열은 보통 모델을 학습해 `P(O_{t+1} | O_t, A_t)`를 파라미터에 넣는다. 우리는 그 대신 실제 웹 탐색에서 모은 transition을 구조화된 메모리로 저장한다.

| 비교 | World model | Ours |
|---|---|---|
| 지식 위치 | fine-tuned model parameter | external transition memory |
| 업데이트 | 재학습 또는 co-training 필요 | 새 경험 삽입/병합/감쇠 |
| 예측 방식 | model generation | retrieval + aggregation + LLM reasoning |
| 강점 | 일반화된 생성 가능 | provenance, inspectability, fast update |
| 위험 | hallucinated next state | retrieval mismatch, memory conflict |

### 메모리 아이템 스키마 초안

가장 중요한 것은 `(O_t, A_i, O_{t+1})`를 raw로 저장하지 않고, 행동 결과를 예측할 수 있는 수준으로 추상화하는 것이다.

```json
{
  "memory_id": "tm_00042",
  "site_family": "shopping",
  "page_state": {
    "page_type": "search_results",
    "stage": "browse_and_select",
    "visible_regions": ["result_grid", "filters", "sort_dropdown"],
    "state_signature": "product results visible with price and title cards"
  },
  "action": {
    "action_type": "click",
    "affordance": "open_product_detail",
    "target_semantics": {
      "role": "link",
      "text_pattern": "product title or card",
      "region": "result_grid"
    }
  },
  "expected_transition": {
    "event_type": "page_navigation_or_detail_render",
    "next_page_type": "product_detail",
    "added_or_visible": ["product_title", "price", "variant_options", "buy_button"],
    "state_delta_summary": "result list is replaced by product detail page"
  },
  "failure_signals": [
    "opens sponsored/ad page",
    "same result list remains unchanged",
    "target element is disabled"
  ],
  "repair_strategy": "go back and select another organic product card",
  "confidence": 0.82,
  "support": {
    "num_observations": 7,
    "success_rate": 0.86,
    "source_tasks": ["webshop_shoes", "webshop_speaker"]
  }
}
```

### 저장할 수 있는 추상화 레벨 후보

처음부터 하나로 고정하지 말고, 여러 후보를 비교해야 한다.

| 레벨 | 저장 형태 | 장점 | 단점 |
|---|---|---|---|
| Raw transition | full DOM/AXTree + action + next DOM/AXTree | 정보 손실 적음 | 너무 길고 사이트별로 brittle |
| Diff transition | changed nodes / URL / modal / event summary | 변화에 집중 | diff 추출이 노이즈에 민감 |
| Element-semantic transition | page_type + role/text/region + expected delta | cross-site 전이 가능 | descriptor가 모호하면 충돌 |
| Stage transition | `search_results -> product_detail` | 강한 일반화 | 세부 action grounding 약함 |
| Affordance transition | `open_detail`, `apply_filter`, `commit_variant` | 사이트를 넘는 skill 단위 | affordance labeling 비용 |
| Probabilistic transition | action별 possible outcomes + confidence | 불확실성 표현 가능 | memory 관리가 복잡 |

## 3. 메모리 구축 파이프라인

### 1단계: 탐색과 transition 수집

웹 환경을 돌리며 기본적으로는 naive tuple을 모은다.

```text
(task, O_t, candidate_actions, selected_action, O_{t+1}, reward, done, metadata)
```

여기서 `candidate_actions`도 저장하는 것이 중요하다. 실행한 action만 알면 "왜 다른 행동을 안 골랐는지"를 학습하기 어렵다.

### 2단계: observation/action/outcome 추상화

`O_t`는 전체 페이지가 아니라 다음처럼 요약한다.

- `page_type`: home, search_results, product_detail, checkout, form, modal, profile, issue_page
- `task_stage`: search, filter, inspect, configure, commit, recover
- `visible_regions`: nav, filters, result_grid, detail_panel, modal, form
- `critical_slots`: price, date, location, variant, submit button, validation message

`A_i`는 좌표나 DOM ID가 아니라 affordance로 바꾼다.

- `open_detail`
- `apply_filter`
- `commit_variant`
- `submit_form`
- `advance_checkout`
- `recover_back`
- `expand_more`

`O_{t+1}`은 전체 next observation 대신 delta를 중심으로 만든다.

- URL changed / unchanged
- page type changed
- modal opened / closed
- results refreshed
- selected option changed
- price changed
- validation error appeared
- target stage reached

### 3단계: memory insertion

새 transition은 바로 넣지 않고, 기존 memory와 비교한다.

- 같은 `page_state + action_affordance`인데 expected transition이 같으면 support를 증가
- outcome이 다르면 possible outcome distribution에 추가
- failure가 반복되면 failure signal로 승격
- site-specific detail은 provenance로 보관하고 retrieval key에서는 약하게 사용

### 4단계: inference에서 사용

에이전트가 현재 observation `O_t`에서 행동 후보 `{A_i}`를 만든다. 각 후보에 대해 transition memory를 검색한다.

```text
for A_i in candidates:
  M_i = retrieve(page_state(O_t), affordance(A_i), target_semantics(A_i))
  O^*_{t+1,i} = aggregate_expected_transition(M_i)
  score_i = judge(goal, O_t, A_i, O^*_{t+1,i}, failure_signals_i)
execute argmax_i score_i
```

핵심은 메모리를 "정답 지시"가 아니라 "행동 결과 가설"로 쓰는 것이다. 실행 후 실제 `O_{t+1}`와 예측 `O^*_{t+1}`를 비교해 confidence를 갱신한다.

## 4. 구체 예시 1: WebShop류 쇼핑 사이트

### 상황

Task: `I want a pair of men's black slip-resistant work shoes, size 10, rubber sole, price lower than $50.00.`

현재 페이지 `O_t`: WebShop homepage

후보 행동:

- `search[men black slip resistant work shoes rubber sole under 50]`
- `click[Men's Shoes category]`
- `click[Sale category]`

### transition memory가 쌓이는 방식

#### Memory 1: 검색 행동

```text
O_t: homepage with search box visible
A: type/search constraint-rich query
O_{t+1}: search_results page, product cards visible, filters visible
```

저장:

```text
page_state: home
action_affordance: submit_search_query
expected_transition: search_results visible with product cards
failure_signal: no results / query unchanged / search box only
```

#### Memory 2: 결과 카드 클릭

```text
O_t: search_results with product cards
A: click plausible product card under budget
O_{t+1}: product_detail with title, price range, color/size selectors
```

저장:

```text
page_state: search_results
action_affordance: open_product_detail
target_semantics: organic product card, not sponsored, has title/price
expected_transition: product_detail page with variant controls
failure_signal: ad page, irrelevant category page, same result list
```

#### Memory 3: variant 선택

```text
O_t: product_detail with color and size options
A: click Black, click Size 10
O_{t+1}: selected variant displayed, price may update
```

저장:

```text
page_state: product_detail
action_affordance: commit_variant_option
expected_transition: selected option state changes; price/stock may update
verification: re-read price and stock after variant selection
failure_signal: option unavailable, price exceeds budget, buy button disabled
```

### 추론 때 어떻게 쓰나

새 task가 `portable bluetooth speaker, waterproof, black, under $30`이면, 모델은 "신발" 예시를 복사하지 않는다. 대신 같은 transition memory를 이렇게 쓴다.

- search query는 hard constraint를 포함해야 한다.
- product card click은 detail page로 넘어가야 한다.
- product detail에서는 hidden attributes와 variant를 확인해야 한다.
- variant 선택 후 price가 바뀔 수 있으니 다시 확인해야 한다.

즉 저장되는 것은 상품명이 아니라 `action -> UI state delta`다.

## 5. 구체 예시 2: Trip.com / Expedia 항공권 검색

웹 에이전트가 자주 실패하는 `result list -> selection / filter / ad detour` 구조와 잘 맞는 설정이다.

Task: `Book the cheapest flight to Tokyo.`

현재 페이지 `O_t`: Trip.com flight search results

후보 행동:

- `click[Select]` on a flight card
- `click[View Deals]` on advertisement
- `click[1 Stop filter]`
- `click[Sort by price]`

### transition memory 후보

#### Memory 1: flight card 선택

```text
page_state: flight_results
action_affordance: select_result_item
target_semantics: role=button/link, text contains Select, context=flight card with price/time
expected_transition: booking step, fare detail, passenger info, or login/booking modal
failure_signal: selected element is ad/promo, disabled, or outside result list
repair_strategy: reject ad region; choose organic flight card
```

#### Memory 2: 광고 버튼 클릭

```text
page_state: flight_results
action_affordance: click_promo_or_ad
target_semantics: ad banner, promo region
expected_transition: promotion page or external deal page
task_relevance: usually negative for booking goal
failure_signal: leaves flight selection workflow
```

#### Memory 3: 필터 적용

```text
page_state: flight_results
action_affordance: apply_filter
target_semantics: checkbox/dropdown in filter sidebar
expected_transition: results list refreshes; result count/prices may change; URL may remain same
verification: detect list refresh or selected filter chip, not only URL change
```

### 여기서 우리 방법이 기존 memory보다 더 보고 싶은 것

기존 memory는 보통 `flight list visible` 상태에서 `Select`를 누르라는 guidance를 준다. 우리는 그 다음까지 본다.

- `Select` 클릭 후 URL 변화가 없어도 modal이 뜨면 성공일 수 있다.
- 광고 영역의 `View Deals`는 role/text가 그럴듯해도 expected transition이 목표와 다르다.
- filter checkbox는 URL 변화 없이 result list만 바꿀 수 있다.

즉 ours의 핵심은 `stage is valid` 다음에 `transition is plausible`을 검증하는 것이다.

## 6. Baseline 조사

### World model / action simulation 계열

| 방법 | 핵심 | 저장/학습되는 것 | 우리와 비교 |
|---|---|---|---|
| Web Agents with World Models (WMA, ICLR 2025) | fine-tuned world model이 다음 관찰 delta를 생성하고 value model이 action 선택 | `I, O_t, A_t -> abstract O_{t+1}`를 Llama-3.1-8B에 학습 | 가장 직접 baseline. 우리는 학습 모델 대신 searchable transition memory |
| WebEvolver (EMNLP 2025) | co-evolving world model이 synthetic trajectory 생성과 inference look-ahead에 사용됨 | agent와 world model을 함께 개선 | 우리보다 학습 중심. 메모리의 inspectability와 fast update를 비교 가능 |
| WAC (arXiv 2026) | action model이 world model에게 전략/결과를 상담하고 judge가 correction | world model + judge + feedback correction chain | action correction baseline. 우리는 correction 근거를 persistent memory로 둠 |
| R-WoM (ICLR 2026) | LLM world model에 external tutorial retrieval을 붙여 hallucination 완화 | tutorial knowledge로 grounded simulation | 외부 문서 기반 retrieval. 우리는 interaction transition 기반 retrieval |
| ATLAS / WebATLAS (2025) | memory-augmented look-ahead action simulation | action simulation + memory + critic | 매우 가까운 baseline 후보. WebArena-Lite에서 비교 가치 높음 |
| WebOperator (2025/26) | action-aware tree search로 invalid/destructive action을 줄임 | search tree와 action filtering | planning/search baseline. 메모리 기반 transition 예측과 비교 |
| ActionEngine (2026) | GUI를 state-machine memory로 축적해 저비용 실행 | state machine memory | GUI state graph baseline. 우리 transition memory와 가장 구조적으로 가까움 |

### Memory 계열

| 방법 | 핵심 | 저장되는 것 | 우리와 비교 |
|---|---|---|---|
| Synapse (ICLR 2024) | trajectory-as-exemplar prompting | full successful trajectories | transition prediction보다 exemplar prompting |
| AWM (2024) | reusable workflow induction | workflow description + workflow trajectory | action outcome이 아니라 routine guidance |
| ReasoningBank (2025/26) | success/failure에서 reasoning memory 추출 | reasoning item, pitfall, lesson | UI transition보다 reasoning strategy |
| SkillRL (2026) | trajectory를 skill로 distill하고 RL 중 evolution | general/task-specific skill bank | 웹 전이 예측보다 policy skill 강화 |
| EchoTrail-GUI (2025) | critic-guided self-exploration으로 GUI memory 구축 | curated successful GUI trajectories/actionable memory | GUI memory baseline. 구현 난이도 확인 필요 |

## 7. 공통 입출력 프로토콜

논문들을 제대로 비교하려면 "이 논문이 좋은가?"보다 먼저 같은 입력을 넣었을 때 각 방법이 무엇을 출력하는지 맞춰봐야 한다. 그래야 우리 방법의 차이가 선명해진다.

### 공통 입력 객체

첫 실험에서는 모든 방법에 아래 형태의 입력을 준다고 가정한다.

```json
{
  "task": "Book the cheapest flight to Tokyo.",
  "observation": {
    "page_type": "flight_results",
    "url_changed_recently": false,
    "visible_regions": ["filter_sidebar", "result_list", "ad_banner", "sort_dropdown"],
    "salient_elements": [
      {"id": "e1", "role": "button", "text": "Select", "region": "result_list", "context": "Flight AA 123, $412, 1 stop"},
      {"id": "e2", "role": "button", "text": "View Deals", "region": "ad_banner", "context": "Sponsored hotel+flight package"},
      {"id": "e3", "role": "checkbox", "text": "1 stop", "region": "filter_sidebar"},
      {"id": "e4", "role": "combobox", "text": "Sort by", "region": "sort_dropdown"}
    ],
    "history": [
      "typed origin and destination",
      "submitted flight search"
    ]
  },
  "candidate_actions": [
    {"action_id": "a1", "op": "click", "target": "e1", "surface": "Select"},
    {"action_id": "a2", "op": "click", "target": "e2", "surface": "View Deals"},
    {"action_id": "a3", "op": "click", "target": "e3", "surface": "1 stop"},
    {"action_id": "a4", "op": "click", "target": "e4", "surface": "Sort by"}
  ]
}
```

이 입력은 실제 DOM 전체가 아니라 비교용으로 정규화한 상태다. 실제 구현에서는 WebArena/Mind2Web/BrowserGym의 관찰을 이 구조로 변환하는 adapter가 필요하다.

### 공통 출력 객체

각 방법의 output을 그대로 비교하기 어렵기 때문에, 평가 harness에서는 아래 슬롯으로 정규화한다.

```json
{
  "retrieved_or_generated_knowledge": "...",
  "predicted_transition_by_action": {
    "a1": "...",
    "a2": "...",
    "a3": "...",
    "a4": "..."
  },
  "selected_action": "a1",
  "selection_reason": "...",
  "verification_rule": "...",
  "memory_update_after_execution": "..."
}
```

중요한 점은 모든 baseline이 이 슬롯을 다 채울 필요는 없다는 것이다. 오히려 빈칸이 그 방법의 한계를 보여준다.

## 8. 같은 입력을 넣으면 각 방법은 무엇을 출력하나

### Flight 결과 페이지 예시

공통 입력은 위의 `flight_results` 상태다. 핵심 distractor는 광고 영역의 `View Deals` 버튼이고, 핵심 subtle transition은 `Select` 클릭 후 URL 변화 없이 booking modal만 뜰 수 있다는 점이다.

| 방법 | 같은 입력에 대한 자연스러운 output | transition을 직접 예측하나 | 우리 비교에서 봐야 할 것 |
|---|---|---|---|
| Vanilla ReAct / CoT | 현재 관찰과 history를 읽고 `click e1` 같은 다음 행동 하나 출력 | 아니오 | 광고 버튼을 action 후보에서 배제하는지 |
| Synapse | 유사한 과거 flight/search trajectory를 exemplar로 넣고 다음 action 출력 | 아니오 | source trajectory의 사이트별 ID/순서가 섞여도 버티는지 |
| AWM | `search flight -> apply constraint -> select result -> fill passenger info` 같은 workflow guidance 출력 | 아니오 | pop-up airport, modal, 광고처럼 intermediate state가 바뀔 때 workflow가 너무 고정되는지 |
| ReasoningBank | "광고/프로모션보다 organic result를 고르고, 선택 후 fare detail을 확인하라" 같은 reasoning lesson 출력 | 부분적 | 교훈은 맞지만 실제 UI 전이를 검증할 수 있는지 |
| SkillRL | 관련 skill을 prompt/policy에 주입하고 skill-conditioned action 출력 | 아니오 | skill이 `select_result`를 말해도 target grounding과 결과 검증이 되는지 |
| WMA | 각 후보 action에 대해 abstract next observation을 생성하고 value model로 action 선택 | 예 | `a1`은 booking/fare detail, `a2`는 promo page, `a3`는 refreshed list처럼 구분하는지 |
| WebEvolver | co-evolving world model이 `O_t, A_i -> O_{t+1}`를 생성하고 inference look-ahead에 사용 | 예 | self-generated world model이 새 사이트의 UI 동역학을 얼마나 정확히 상상하는지 |
| WAC | action model이 world model에게 전략을 물어보고, judge가 simulated outcome을 보고 correction feedback 출력 | 예 | 위험 action을 실행 전에 교정하는지, correction이 persistent memory로 남는지 |
| R-WoM | 튜토리얼 검색으로 grounded world model simulation을 만들고 next-state/reward estimate 출력 | 예 | tutorial 문서가 있는 앱/웹에서는 강하지만 interaction-specific 변화도 잡는지 |
| WebATLAS | cognitive map + experience memory를 바탕으로 후보 action roll-out과 critic score 출력 | 예 | 매우 가까운 baseline. 다만 memory item이 inspect 가능한 transition rule인지 확인 필요 |
| WebOperator | tree-search branch, reward/safety score, backtracking plan 출력 | 간접적 | action의 irreversible/risky 여부와 backtrack 가능성을 잘 다루는지 |
| ActionEngine | offline crawl로 만든 state-machine path를 Python program으로 합성 | 간접적 | state graph가 있는 사이트에서는 강하지만 처음 보는 사이트/동적 modal에 어떻게 repair하는지 |
| EchoTrail-GUI | reward model이 검증한 성공 trajectory를 retrieval해 in-context memory로 주입 | 아니오 | 성공 trajectory retrieval이 transition 예측 없이도 distractor를 줄이는지 |
| Ours | 후보 action별 transition memory를 검색해 expected delta, failure signal, verification rule을 출력 | 예 | `Select -> modal/detail 가능`, `View Deals -> promo detour`, `Filter -> list refresh`를 명시적으로 구분하는지 |

이 표에서 핵심은 WMA/WebEvolver/WAC/R-WoM/WebATLAS는 우리와 같은 질문을 일부 이미 한다는 점이다. 하지만 대개 `world model generation`이 중심이고, 메모리의 단위가 `검증 가능한 transition rule`로 정리되어 있지는 않다. 반대로 Synapse/AWM/ReasoningBank/SkillRL은 메모리 연구로 강하지만, 같은 후보 행동들을 놓고 "각 행동을 하면 화면이 어떻게 달라질지"를 출력하지 않는다.

### Shopping product detail 예시

두 번째 공통 입력은 상품 상세 페이지다.

```text
task: Buy black waterproof bluetooth speaker under $30.
O_t: product_detail page, color dropdown, warranty checkbox, Add to Cart button, price $27.99 visible
candidates:
  a1 = click color dropdown
  a2 = click black option
  a3 = click warranty checkbox
  a4 = click Add to Cart
```

여기서 중요한 전이는 `a2` 후 가격/재고/버튼 상태가 바뀔 수 있고, `a3`은 가격을 $30 이상으로 올릴 수 있으며, `a4`는 cart modal을 띄우거나 바로 cart page로 이동할 수 있다는 점이다.

| 방법 | 이 예시에서 기대되는 output | 놓치기 쉬운 부분 |
|---|---|---|
| AWM/ReasoningBank | product option을 고르고 add-to-cart로 진행하는 workflow/lesson | 옵션 선택 후 price 재검증 |
| ReasoningBank/SkillRL | "조건을 만족하는지 확인하고 구매 전 가격을 재확인" lesson/skill | 어떤 UI action이 가격을 바꾸는지 |
| WMA/WebEvolver/WAC | 각 action 후 next observation simulation | 실제 옵션별 가격을 hallucinate할 위험 |
| ActionEngine/WebATLAS | 과거 탐색으로 얻은 product-detail action path 또는 roll-out | 같은 product detail 구조가 아닐 때 conflict |
| Ours | `commit_variant_option -> selected option + price/stock may update`, `add_warranty -> price increases`, `add_to_cart -> cart modal/page` | memory conflict를 outcome distribution으로 관리해야 함 |

## 9. 더 발전시키려면 당장 해야 하는 일

### A. 같은 input을 만드는 adapter부터 필요하다

논문별 구현이 다 다르기 때문에 첫 번째 산출물은 모델이 아니라 `common IO harness`다.

```text
raw WebArena/Mind2Web/BrowserGym state
  -> normalized observation
  -> candidate action list
  -> method-specific prompt/input
  -> normalized output slots
```

이 adapter가 있으면 "논문 A는 workflow를 출력하고, 논문 B는 next observation을 출력한다"를 같은 화면에서 비교할 수 있다.

### B. offline dataset만으로는 counterfactual transition이 부족하다

Mind2Web은 logged trajectory 중심이라 `실제로 실행한 action`의 다음 상태는 알 수 있지만, 같은 상태에서 다른 후보 action `a2, a3, a4`를 눌렀을 때의 결과는 없다. 그런데 우리 질문은 후보 action별 전이가 중요하다.

따라서 데이터는 두 층으로 나누는 게 좋다.

| 데이터 | 할 수 있는 평가 | 한계 |
|---|---|---|
| Mind2Web offline | gold action ranking, logged action next-stage prediction | 후보 action별 counterfactual next state 없음 |
| WebArena/BrowserGym interactive | 같은 `O_t`에서 여러 후보 action을 fork 실행해 transition 수집 | 환경 세팅과 reset/fork 비용 |
| 자체 Playwright crawl | 회의용 trace와 transition memory 예시 만들기 쉬움 | benchmark score로 주장하기 어려움 |

초기에는 Mind2Web으로 action ranking과 memory retrieval을 빨리 검증하고, WebArena/BrowserGym에서 작은 subset을 만들어 candidate별 transition을 실제로 수집하는 게 현실적이다.

### C. baseline 구현 난이도별로 나누자

바로 전부 재현하려고 하면 늪이다. 우선 output type을 맞추는 v0가 중요하다.

| 단계 | 구현할 것 | 목적 |
|---|---|---|
| v0 | Vanilla CoT, Flat trajectory retrieval, AWM API prototype, ReasoningBank-style, WMA API prototype, Ours | 같은 input에 대해 output 형태 차이 확인 |
| v1 | WebArena/BrowserGym에서 candidate action fork 실행 | transition label 확보 |
| v2 | WebATLAS/ActionEngine/R-WoM 코드 또는 prompt 재현 가능성 확인 | 가장 가까운 최신 baseline 비교 |
| v3 | ours memory insertion/merge/conflict 관리 실험 | 논문 기여점 만들기 |

### D. 각 baseline에 필요한 method-specific output schema

실험 코드에서는 모든 방법이 아래 중 하나의 JSON을 내도록 강제하면 된다.

```json
{
  "method": "ReasoningBank-style",
  "retrieved_lesson": "avoid sponsored deal detours and choose organic flight results",
  "pitfall": "View Deals may lead to promo or package pages",
  "selected_action": "a1",
  "missing_output": ["candidate-wise next transition", "verification rule for modal"]
}
```

```json
{
  "method": "WMA API prototype",
  "predictions": {
    "a1": "A fare detail or booking modal appears.",
    "a2": "A sponsored deal or external promo page opens.",
    "a3": "The result list refreshes with one-stop flights.",
    "a4": "A sort menu opens."
  },
  "selected_action": "a1",
  "missing_output": ["provenance", "memory update", "conflict tracking"]
}
```

```json
{
  "method": "Ours",
  "retrieved_transition_memories": {
    "a1": ["flight_results + select_result_item -> booking_modal_or_fare_detail"],
    "a2": ["result_page + click_promo_or_ad -> promo_detour"],
    "a3": ["result_page + apply_filter -> result_list_refresh"],
    "a4": ["result_page + open_sort_dropdown -> menu_expanded"]
  },
  "selected_action": "a1",
  "verification_rule": "After click, accept URL navigation, fare-detail panel, or booking modal as progress; reject promo/external page.",
  "memory_update_after_execution": "increment support for observed transition or add alternate outcome."
}
```

### E. 이 연구의 진짜 claim 후보

현재 상태에서 가장 강한 claim은 이것이다.

> Web agent memory should not only tell the agent what to do; it should predict what the environment will do back.

조금 더 논문화하면 다음 세 가지다.

1. `Action-output memory`: memory item의 핵심 값을 action sequence가 아니라 action-conditioned state delta로 바꾼다.
2. `Candidate-wise transition retrieval`: 하나의 retrieved workflow를 따르는 대신, 현재 후보 action 각각에 대해 transition memory를 검색한다.
3. `Verification-aware execution`: action 실행 후 실제 변화와 expected transition을 비교해 success/failure/recovery와 memory update를 동시에 수행한다.

## 10. 첫 구현 범위

### 공통 벤치마크 후보

1. `Mind2Web`

장점: offline step prediction / action ranking 분석이 쉽다. 이미 trajectory와 split이 잘 정의되어 있다.

단점: 실제 실행 후 recovery를 보기 어렵다.

2. `WebArena-Lite` 또는 `WebArena subset`

장점: 실제 interactive transition과 recovery를 볼 수 있다.

단점: 환경 세팅이 무겁다.

3. `BrowserGym / MiniWoB++`

장점: 빠른 반복과 transition collection에 좋다.

단점: 실제 웹 다양성은 약하다.

첫 1-2주에는 `Mind2Web offline + WebArena-Lite small subset` 조합이 좋다. Mind2Web으로 retrieval/action ranking을 빠르게 검증하고, 회의용 예시는 WebArena-Lite나 자체 Playwright crawl로 시각화한다.

### 구현할 baseline v0

1. Flat trajectory retrieval

Synapse 스타일. 현재 task/observation과 유사한 trajectory step을 그대로 가져온다.

2. Workflow memory

AWM 스타일. trajectory에서 high-level workflow만 뽑아 prompt에 넣는다.

3. ReasoningBank-style

성공/실패 trajectory에서 lesson/pitfall을 추출해 prompt에 넣는다. 후보 action별 expected transition은 일부러 비워 두어 우리 방법과 차이를 보이게 한다.

4. Prompted world model

fine-tuning 없이 LLM에게 `O_t, A_i -> predicted delta`를 물어본다. WMA를 바로 재현하기 어렵다면 이걸 world model baseline v0로 둔다.

5. Ours v0

Transition memory retrieval:

```text
index key = page_state + action_affordance + target_semantics
value = expected_transition + failure_signals + confidence
```

## 11. 평가 지표

단순 task success만 보면 왜 좋아졌는지 모른다. 최소한 아래 지표를 같이 봐야 한다.

| 지표 | 의미 |
|---|---|
| `Next-stage prediction accuracy` | action 후 page/stage가 맞게 예측됐는가 |
| `Delta type accuracy` | modal, URL change, list refresh, option update 등을 맞췄는가 |
| `Action ranking accuracy` | 후보 행동 중 gold/valid action을 높게 골랐는가 |
| `Invalid transition rate` | 실행하면 목표에서 벗어나는 action을 얼마나 줄였는가 |
| `Recovery success` | 예측과 실제 결과가 다를 때 잘 복구하는가 |
| `Memory conflict rate` | 같은 key에서 충돌 outcome이 얼마나 자주 발생하는가 |
| `Human inspectability` | memory item이 사람이 보고 수정 가능한가 |

## 12. 메모리 관리 이슈

### Memory conflict

같은 `page_state + action_affordance`라도 사이트에 따라 결과가 다를 수 있다. 하나의 expected transition으로 덮으면 안 된다.

처리 후보:

- possible outcomes를 distribution으로 저장
- site_family/domain/page_type 조건으로 분기
- confidence와 support를 별도 관리
- 최근 관찰과 더 맞는 memory를 우선

### Retrieval miss

검색이 안 되면 world model처럼 일반화해야 한다.

처리 후보:

- stage-level fallback
- affordance-level fallback
- prompted world model fallback
- exploratory action with risk filter

### Granularity

`O`와 `A`의 레벨이 너무 낮으면 brittle하고, 너무 높으면 action 선택에 못 쓴다.

초기 가설:

> page_state는 stage-level, action은 affordance-level, outcome은 delta-level로 둔다.

즉 `Search results page + click organic product card -> product detail appears` 정도가 첫 균형점이다.

## 13. 1-2주 실행 계획

### 1-3일차: baseline survey와 taxonomy

- WMA, WebEvolver, WAC, R-WoM, ATLAS/WebATLAS, AWM, ReasoningBank를 같은 표로 정리
- 각 방법이 실제로 무엇을 저장하거나 학습하는지 1개 예시로 재구성
- 후보 benchmark와 실행 난이도 확인

산출물:

- baseline comparison table
- `what gets stored` examples for 2 web tasks

### 4-7일차: 데이터 수집/표현 v0

- Mind2Web 또는 WebArena-Lite에서 `(O_t, A_t, O_{t+1})` 샘플 100-300개 추출
- observation abstraction prompt 작성
- action affordance labeling prompt 작성
- delta extraction prompt 작성

산출물:

- transition memory JSONL
- example memory browser script or notebook

### 8-10일차: baseline v0 구현

- Flat retrieval
- ReasoningBank-style retrieval
- Prompted world model
- Ours transition memory retrieval

산출물:

- 같은 task 20-50개에서 action ranking 비교
- transition prediction accuracy 비교

### 11-14일차: 회의용 예시 2개 준비

예시 1: WebShop류 쇼핑

- search -> result -> product detail -> variant -> buy
- variant selection 후 price/stock 변화 예측 강조

예시 2: Trip.com/flight류

- result list -> select flight / ad distractor / filter refresh
- URL 변화 없는 modal과 ad distractor 강조

산출물:

- 각 방법이 무엇을 retrieval하는지 side-by-side
- ours가 어떤 memory를 찾고 어떤 next transition을 예측하는지 trace

## 14. 회의에서 던질 핵심 주장

### Claim 1

기존 memory는 `what to do`를 저장한다. 우리가 저장하려는 것은 `what happens if we do it`이다.

### Claim 2

웹에서는 action correctness가 action 자체보다 transition verification에 의해 결정되는 경우가 많다.

### Claim 3

Learned world model은 강하지만 업데이트와 검증이 어렵다. Transition memory는 약간 덜 general할 수 있지만, 빠르게 쌓이고 inspect 가능하며 conflict를 명시적으로 관리할 수 있다.

### Claim 4

Workflow와 reasoning memory가 what-to-do mismatch를 줄였다면, 다음 단계는 transition mismatch를 줄이는 것이다.

## 15. 참고 baseline 링크

- [Web Agents with World Models, ICLR 2025](https://openreview.net/forum?id=moWiYJuSGF)
- [WebEvolver, EMNLP 2025](https://aclanthology.org/2025.emnlp-main.454/)
- [World-Model-Augmented Web Agents with Action Correction, arXiv 2026](https://arxiv.org/abs/2602.15384)
- [R-WoM: Retrieval-augmented World Model For Computer-use Agents, ICLR 2026](https://arxiv.org/abs/2510.11892)
- [ATLAS: Actor-Critic Task-Completion with Look-ahead Action Simulation, arXiv 2025](https://arxiv.org/abs/2510.22732)
- [ActionEngine: Programmatic GUI Agents via State Machine Memory, arXiv 2026](https://arxiv.org/abs/2602.20502)
- [WebOperator: Action-Aware Tree Search for Autonomous Agents in Web Environment, arXiv 2025](https://arxiv.org/abs/2512.12692)
- [EchoTrail-GUI: Building Actionable Memory for GUI Agents, arXiv 2025/2026](https://arxiv.org/abs/2512.19396)
- [Synapse, ICLR 2024](https://arxiv.org/abs/2306.07863)
- [Agent Workflow Memory, arXiv 2024](https://arxiv.org/abs/2409.07429)
- [ReasoningBank, arXiv 2025](https://arxiv.org/abs/2509.25140)
- [Mind2Web benchmark](https://arxiv.org/abs/2306.06070)
- [WebArena benchmark](https://arxiv.org/abs/2307.13854)
