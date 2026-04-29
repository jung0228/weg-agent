# Web Transition Memory Baseline IO Examples

작성일: 2026-04-29

목표는 같은 웹 예시를 두고 각 baseline이 무엇을 `저장`하고, inference 때 무엇을 `입력`으로 받고, 무엇을 `출력`하는지 단계별로 보여주는 것이다.

내일 미팅에서는 방법론 설명보다 이 표와 흐름을 보여주는 것이 더 중요하다.

## 0. 비교할 baseline

| baseline | 저장 단위 | 핵심 질문 |
|---|---|---|
| Synapse-style | full trajectory exemplar | "과거에 비슷한 태스크를 어떻게 풀었나?" |
| AWM API prototype | reusable workflow | "반복되는 sub-routine은 무엇인가?" |
| ReasoningBank-style | reasoning lesson | "성공/실패 경험에서 뽑은 교훈은 무엇인가?" |
| WMA API prototype | imagined next observation | "이 action을 하면 다음 상태가 어떻게 될까?" |
| RAP-style | imagined rollout / planning trace | "여러 상상 rollout 중 무엇이 가장 유망한가?" |
| Ours | transition memory | "이 action을 하면 어떤 UI delta가 생기고, 무엇을 검증해야 하나?" |

## 0-1. 입출력 스텝별로 기억하는 법

각 baseline은 아래 5칸으로 강제로 맞춰서 기억한다. 이 구조로 보면 방법마다 무엇을 잘하고 무엇을 비워두는지가 바로 보인다.

| 단계 | 질문 | 기록할 것 |
|---:|---|---|
| 1 | 무엇을 저장하나? | `memory_type`, source trajectory, workflow, lesson, transition rule |
| 2 | inference 때 무엇을 입력으로 받나? | `task`, `O_t`, `candidate_actions`, retrieved memory |
| 3 | 무엇을 출력하나? | `memory_view`, selected action, predicted transition, pitfall/strategy, verification rule |
| 4 | 무엇을 못 출력하나? | `missing_output`에 candidate-wise transition, failure signal, update rule 같은 빈칸 기록 |
| 5 | 실행 후 무엇을 업데이트하나? | actual delta, success/failure, memory confidence, conflict |

공통 JSON 슬롯은 이렇게 둔다.

```json
{
  "method": "baseline_name",
  "stored_unit": "...",
  "inference_input": {
    "task": "...",
    "observation": "O_t",
    "candidate_actions": ["A_1", "A_2"],
    "retrieved_memory": "..."
  },
  "output": {
    "memory_view": "...",
    "retrieved_or_generated_knowledge": "...",
    "predicted_transition_by_action": {},
    "selected_action": "...",
    "verification_rule": "...",
    "missing_output": []
  },
  "post_action_update": "..."
}
```

내일 보여줄 핵심은 `Synapse/AWM/ReasoningBank`는 1-3번은 채우지만 `memory_view`가 trajectory/workflow/lesson 쪽으로 기울고, `WMA/RAP`는 transition을 상상하지만 실제 UI 검증과 memory update가 약하며, `Ours`는 `expected_transition`, `failure_signal`, `verification_rule`을 transition memory 중심으로 채운다는 점이다.

## 1. Example A: Flight Result Page

### 1.1 공통 상황

```json
{
  "task": "Book the cheapest flight to Tokyo.",
  "observation": {
    "page_type": "flight_results",
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
    {"id": "a1", "op": "click", "target": "e1", "surface": "Select"},
    {"id": "a2", "op": "click", "target": "e2", "surface": "View Deals"},
    {"id": "a3", "op": "click", "target": "e3", "surface": "1 stop"},
    {"id": "a4", "op": "click", "target": "e4", "surface": "Sort by"}
  ]
}
```

핵심 관찰:

- `a1`은 정상 flight selection일 가능성이 높다.
- `a2`는 광고/프로모션 detour일 가능성이 높다.
- `a3`은 결과 리스트 refresh를 만들지만, URL은 안 바뀔 수 있다.
- `a4`는 정렬 메뉴를 열 뿐, booking progress는 아니다.

## 2. Flight Example: Baseline별 저장 단위와 입출력

### 2.1 Synapse-style retrieval

#### 저장 단위

Synapse-style memory는 과거 성공 trajectory 전체를 exemplar로 저장한다.

```json
{
  "memory_type": "trajectory_exemplar",
  "source_task": "Find and book a flight from New York to San Francisco.",
  "trajectory": [
    {
      "observation": "flight search form visible",
      "action": "type origin, destination, dates"
    },
    {
      "observation": "flight results list visible",
      "action": "click Select on the cheapest suitable flight"
    },
    {
      "observation": "fare detail page visible",
      "action": "continue to passenger information"
    }
  ],
  "retrieval_key": "flight booking, search result, select flight"
}
```

#### Inference input

```json
{
  "task": "Book the cheapest flight to Tokyo.",
  "current_observation": "flight result page with Select, View Deals, filter, sort",
  "retrieved_exemplar": "past flight booking trajectory"
}
```

#### Output

```json
{
  "selected_action": "click e1",
  "reason": "A similar trajectory selected a flight by clicking Select on a result card."
}
```

#### 단계별 흐름

1. 현재 task와 과거 task metadata를 embedding으로 비교한다.
2. 비슷한 flight booking trajectory를 가져온다.
3. prompt에 과거 trajectory와 현재 observation을 넣는다.
4. LLM이 다음 action으로 `click Select`를 생성한다.

#### 이 예시에서 약한 점

Synapse는 `View Deals`가 광고라는 것을 직접 transition으로 예측하지 않는다. 과거 trajectory가 `Select`를 눌렀으니 현재도 그럴듯한 `Select`를 고르는 방식이다.

### 2.2 AWM API prototype

#### 저장 단위

AWM API prototype은 과거 trajectory에서 reusable workflow를 추출해 저장한다.

```json
{
  "memory_type": "workflow",
  "workflow_name": "book_flight_from_results",
  "description": "Given a flight result page, compare available flights and select a suitable organic flight result before moving to passenger details.",
  "steps": [
    "Verify that the page shows flight search results.",
    "Ignore promotional banners or unrelated deal widgets.",
    "Select the flight result that best satisfies the user's constraints.",
    "Proceed to fare detail or passenger information."
  ],
  "variables": ["destination", "price_constraint", "flight_card"]
}
```

#### Inference input

```json
{
  "task": "Book the cheapest flight to Tokyo.",
  "current_observation": "flight result page",
  "retrieved_workflow": "book_flight_from_results"
}
```

#### Output

```json
{
  "selected_action": "click e1",
  "workflow_step": "Select the flight result that best satisfies the user's constraints."
}
```

#### 단계별 흐름

1. 현재 task가 flight booking 계열임을 보고 workflow를 검색한다.
2. workflow가 "광고를 무시하고 flight result를 고르라"고 guidance를 준다.
3. LLM이 현재 observation에서 workflow step에 맞는 action을 고른다.
4. `click e1`을 출력한다.

#### 이 예시에서 약한 점

AWM은 workflow guidance가 강하지만, `click e1` 이후 실제로 URL navigation이 일어나는지, booking modal이 뜨는지, fare detail panel이 뜨는지는 output하지 않는다.

### 2.3 ReasoningBank-style

#### 저장 단위

ReasoningBank-style memory는 성공/실패 trajectory에서 일반화된 reasoning lesson을 추출해 저장한다.

```json
{
  "memory_type": "reasoning_lesson",
  "source": "failed/successful flight booking trajectories",
  "lesson": "On flight result pages, prefer organic result cards over sponsored deal banners. If the task is to book a flight, a deal banner may lead to package or ad detours.",
  "applicability": {
    "domain": "travel",
    "page_type": "flight_results",
    "signals": ["organic result list", "sponsored banner", "Select button", "View Deals button"]
  },
  "suggested_strategy": [
    "identify organic flight result cards",
    "avoid sponsored package widgets unless task explicitly asks for deals",
    "choose the flight that satisfies price/time constraints"
  ]
}
```

#### Inference input

```json
{
  "task": "Book the cheapest flight to Tokyo.",
  "current_observation": "flight results list visible with Select buttons and ad banner",
  "candidate_actions": ["a1", "a2", "a3", "a4"],
  "retrieved_lesson": "prefer organic flight result cards; avoid sponsored deal detours"
}
```

#### Output

```json
{
  "pitfall": "View Deals is likely a sponsored detour.",
  "strategy": "Use the organic result list and pick the cheapest suitable flight.",
  "selected_action": "click e1",
  "reason": "e1 is a Select button inside the organic result list, while e2 is in an ad banner."
}
```

#### 단계별 흐름

1. 현재 task와 observation에서 `flight_results`, `sponsored banner`, `Select` 신호를 뽑는다.
2. 성공/실패에서 추출된 relevant lesson을 검색한다.
3. lesson이 `View Deals` 같은 광고성 detour를 피하라고 알려준다.
4. LLM이 lesson을 근거로 `click e1`을 선택한다.

#### 이 예시에서 약한 점

ReasoningBank-style은 "광고를 피하고 organic result를 고르라"는 교훈을 잘 준다. 하지만 `click e1` 후 booking modal이 뜨는지, URL 변화가 없어도 성공으로 볼지 같은 action-conditioned transition verification은 직접 저장하지 않는다.

### 2.4 WMA API prototype

#### 저장 단위

WMA API prototype에서는 별도 memory를 저장하지 않는다. LLM에게 현재 상태와 후보 action을 넣고 next transition을 직접 묻는다.

학습된 WMA를 쓰면 저장 단위는 model parameter다.

```json
{
  "memory_type": "none_or_model_parameter",
  "world_model_function": "predict_delta(task, O_t, A_i) -> O*_{t+1}"
}
```

#### Inference input

```json
{
  "task": "Book the cheapest flight to Tokyo.",
  "current_observation": "flight result page with candidate actions",
  "candidate_actions": ["a1", "a2", "a3", "a4"]
}
```

#### Output

```json
{
  "predicted_transition_by_action": {
    "a1": "A fare detail page or booking modal appears for the selected flight.",
    "a2": "A sponsored package or external deal page opens.",
    "a3": "The result list refreshes to show one-stop flights; URL may remain unchanged.",
    "a4": "A sort dropdown menu opens."
  },
  "selected_action": "a1",
  "selection_reason": "a1 is most likely to advance the booking task."
}
```

#### 단계별 흐름

1. 후보 action `a1-a4`를 만든다.
2. 각 후보에 대해 `O_t, A_i -> O*_{t+1}`를 world model에 묻는다.
3. predicted next state가 task progress에 맞는지 scoring한다.
4. `a1`을 선택한다.

#### 이 예시에서 약한 점

WMA API prototype은 후보별 전이를 직접 출력하므로 우리와 질문이 가깝다. 다만 예측 근거가 실제 memory item이 아니라 LLM/world model 내부에 있어 hallucination, provenance, 업데이트 문제가 있다.

### 2.5 Ours: Transition Memory

#### 저장 단위

Ours는 action-conditioned UI transition을 memory item으로 저장한다.

```json
{
  "memory_type": "transition_memory",
  "key": {
    "page_state": "flight_results",
    "action_affordance": "select_result_item",
    "target_semantics": "Select button inside organic flight card"
  },
  "value": {
    "expected_transition": "booking modal, fare detail panel, or passenger information step appears",
    "failure_signals": [
      "external promo page opens",
      "same result list remains unchanged",
      "selected element is inside ad banner"
    ],
    "verification_rule": "Accept modal or fare detail as progress even if URL does not change.",
    "repair_strategy": "go back and choose another organic flight card",
    "support": {"num_observations": 6, "success_rate": 0.83}
  }
}
```

추가로 다른 후보 action에 대한 memory도 저장된다.

```json
[
  {
    "key": {"page_state": "flight_results", "action_affordance": "click_promo_or_ad"},
    "value": {"expected_transition": "promo or external deal page", "task_relevance": "negative"}
  },
  {
    "key": {"page_state": "flight_results", "action_affordance": "apply_filter"},
    "value": {"expected_transition": "result list refresh; URL may remain unchanged", "verification_rule": "check filter chip or result count"}
  },
  {
    "key": {"page_state": "flight_results", "action_affordance": "open_sort_dropdown"},
    "value": {"expected_transition": "sort menu expands", "task_relevance": "neutral"}
  }
]
```

#### Inference input

```json
{
  "task": "Book the cheapest flight to Tokyo.",
  "current_observation": "flight result page",
  "candidate_actions": ["a1", "a2", "a3", "a4"],
  "retrieved_transition_memories": {
    "a1": "select_result_item memory",
    "a2": "click_promo_or_ad memory",
    "a3": "apply_filter memory",
    "a4": "open_sort_dropdown memory"
  }
}
```

#### Output

```json
{
  "predicted_transition_by_action": {
    "a1": {
      "expected_delta": "booking modal/fare detail/passenger info appears",
      "failure_signal": "promo page, unchanged result list",
      "verification_rule": "modal without URL change can still be success"
    },
    "a2": {
      "expected_delta": "promo detour",
      "failure_signal": "leaves flight booking workflow",
      "verification_rule": "reject"
    },
    "a3": {
      "expected_delta": "result list refresh",
      "failure_signal": "no selected filter chip and no list change",
      "verification_rule": "check DOM/list diff, not only URL"
    },
    "a4": {
      "expected_delta": "sort dropdown opens",
      "failure_signal": "none",
      "verification_rule": "does not advance booking by itself"
    }
  },
  "selected_action": "a1",
  "post_action_update_rule": "compare actual UI delta with expected delta and update support/confidence"
}
```

#### 단계별 흐름

1. 현재 observation을 `page_state=flight_results`로 추상화한다.
2. 후보 action을 affordance로 바꾼다.
3. 각 후보별로 transition memory를 검색한다.
4. 후보별 expected delta, failure signal, verification rule을 만든다.
5. task progress에 가장 맞는 `a1`을 선택한다.
6. 실행 후 실제 `O_{t+1}`와 expected delta를 비교한다.
7. 성공하면 support/confidence를 올리고, 다르면 alternate outcome 또는 failure signal로 memory를 업데이트한다.

#### 이 예시에서 강한 점

Ours는 action을 고르는 것에서 끝나지 않는다. `click Select` 후 어떤 상태 변화가 성공인지까지 미리 가지고 있기 때문에, URL 변화 없는 modal 같은 subtle transition을 성공으로 인정할 수 있고, 광고 detour를 failure로 기록할 수 있다.

## 3. Example B: Shopping Product Detail

### 3.1 공통 상황

```json
{
  "task": "Buy black waterproof bluetooth speaker under $30.",
  "observation": {
    "page_type": "product_detail",
    "visible_regions": ["product_summary", "variant_options", "purchase_box"],
    "critical_slots": {
      "price": "$27.99",
      "color": "not selected",
      "warranty": "unchecked",
      "cart_state": "empty"
    }
  },
  "candidate_actions": [
    {"id": "b1", "op": "click", "surface": "Black color option"},
    {"id": "b2", "op": "click", "surface": "Add 2-year warranty"},
    {"id": "b3", "op": "click", "surface": "Add to Cart"}
  ]
}
```

핵심 관찰:

- color option을 누르면 selected state, stock, price가 바뀔 수 있다.
- warranty는 total price를 올려 budget constraint를 깨뜨릴 수 있다.
- Add to Cart는 cart page 이동이 아니라 cart modal만 띄울 수 있다.

## 4. Shopping Example: Baseline별 출력 차이

### 4.1 Synapse-style

#### 저장 단위

```json
{
  "memory_type": "trajectory_exemplar",
  "source_task": "Buy a red wireless mouse under $20.",
  "trajectory": [
    {"observation": "product detail page", "action": "select required color"},
    {"observation": "option selected", "action": "verify price"},
    {"observation": "price within budget", "action": "click Add to Cart"}
  ]
}
```

#### Output

```json
{
  "selected_action": "click b1",
  "reason": "Past trajectory selected the required variant before adding to cart."
}
```

#### 단계별 흐름

1. 유사한 product purchase trajectory를 검색한다.
2. 현재 task가 black speaker이므로 variant 선택이 필요하다고 본다.
3. `click b1`을 출력한다.

#### 약점

`b2` warranty가 price를 올릴 수 있다는 transition을 후보별로 비교하지 않는다.

### 4.2 AWM API prototype

#### 저장 단위

```json
{
  "memory_type": "workflow",
  "workflow_name": "purchase_product_with_constraints",
  "steps": [
    "Open product detail page.",
    "Select required options such as color or size.",
    "Verify price and availability after options are selected.",
    "Add the item to cart if constraints are satisfied."
  ]
}
```

#### Output

```json
{
  "selected_action": "click b1",
  "workflow_step": "Select required options such as color or size."
}
```

#### 단계별 흐름

1. purchase workflow를 검색한다.
2. workflow가 옵션 선택 후 가격 확인을 지시한다.
3. 현재 단계에서는 black option 선택이 필요하므로 `b1`을 고른다.

#### 약점

workflow는 "가격 확인"을 말하지만, 어떤 action이 price update를 유발하는지는 memory value에 명시되어 있지 않다.

### 4.3 ReasoningBank-style

#### 저장 단위

```json
{
  "memory_type": "reasoning_lesson",
  "source": "failed/successful shopping trajectories",
  "lesson": "On product detail pages, select required variants before adding to cart. Re-check price and availability after option changes, and avoid optional add-ons that can violate budget constraints.",
  "applicability": {
    "domain": "shopping",
    "page_type": "product_detail",
    "signals": ["variant option", "warranty checkbox", "add to cart button", "budget constraint"]
  },
  "suggested_strategy": [
    "select the required color/size first",
    "avoid optional warranty unless requested",
    "verify price before adding to cart"
  ]
}
```

#### Output

```json
{
  "pitfall": "Warranty may increase the price beyond the budget.",
  "strategy": "Select the required black option first, then re-check price before adding to cart.",
  "selected_action": "click b1"
}
```

#### 단계별 흐름

1. 현재 task에서 `black`, `under $30`, `product detail` 신호를 뽑는다.
2. shopping 실패/성공 lesson 중 variant와 budget 관련 memory를 검색한다.
3. warranty는 budget risk가 있으므로 피하라는 pitfall을 얻는다.
4. black option을 먼저 선택하라는 strategy에 따라 `click b1`을 출력한다.

#### 약점

ReasoningBank-style은 option 선택과 budget 주의라는 교훈을 준다. 하지만 `b1`, `b2`, `b3` 각각이 어떤 UI delta를 만들고 어떤 검증 규칙이 필요한지는 별도 transition memory처럼 구조화하지 않는다.

### 4.4 WMA API prototype

#### 저장 단위

```json
{
  "memory_type": "none_or_model_parameter",
  "world_model_function": "predict_delta(task, O_t, A_i)"
}
```

#### Output

```json
{
  "predicted_transition_by_action": {
    "b1": "The black option becomes selected; price or stock may update.",
    "b2": "Warranty is added and total price increases.",
    "b3": "Cart modal or cart page appears."
  },
  "selected_action": "b1",
  "reason": "The product must be black before adding to cart."
}
```

#### 단계별 흐름

1. 각 후보 action의 next state를 LLM/world model에 묻는다.
2. `b1`은 task constraint를 만족시키는 방향이라고 판단한다.
3. `b2`는 budget risk가 있으므로 피한다.
4. `b1`을 출력한다.

#### 약점

실제 black option이 가격을 얼마로 바꾸는지 hallucinate할 수 있다. 또한 예측 근거가 memory item으로 남지 않는다.

### 4.5 Ours

#### 저장 단위

```json
[
  {
    "memory_type": "transition_memory",
    "key": {
      "page_state": "product_detail",
      "action_affordance": "commit_variant_option",
      "target_semantics": "required color option"
    },
    "value": {
      "expected_transition": "selected option state changes; price/stock/buy-button may update",
      "verification_rule": "re-read price and availability after variant selection",
      "failure_signals": ["option unavailable", "price exceeds budget", "buy button disabled"]
    }
  },
  {
    "memory_type": "transition_memory",
    "key": {
      "page_state": "product_detail",
      "action_affordance": "add_warranty"
    },
    "value": {
      "expected_transition": "warranty selected; total price increases",
      "verification_rule": "reject if total price exceeds user budget",
      "failure_signals": ["budget constraint violated"]
    }
  },
  {
    "memory_type": "transition_memory",
    "key": {
      "page_state": "product_detail",
      "action_affordance": "add_to_cart"
    },
    "value": {
      "expected_transition": "cart modal or cart page appears",
      "verification_rule": "accept modal as cart progress even without URL change",
      "failure_signals": ["cart count unchanged", "validation error", "required option missing"]
    }
  }
]
```

#### Output

```json
{
  "predicted_transition_by_action": {
    "b1": {
      "expected_delta": "black selected; price/stock may update",
      "verification_rule": "re-read price before proceeding"
    },
    "b2": {
      "expected_delta": "warranty added; price increases",
      "verification_rule": "reject if price > $30"
    },
    "b3": {
      "expected_delta": "cart modal/page appears",
      "failure_signal": "required option missing if color not selected"
    }
  },
  "selected_action": "b1"
}
```

#### 단계별 흐름

1. 현재 page를 `product_detail`로 추상화한다.
2. 후보 action을 `commit_variant_option`, `add_warranty`, `add_to_cart` affordance로 변환한다.
3. 각 affordance에 맞는 transition memory를 검색한다.
4. `b1`은 task constraint를 만족시키지만 price 재검증이 필요하다고 판단한다.
5. `b2`는 budget violation risk가 있으므로 낮게 평가한다.
6. `b3`는 required option missing 가능성이 있어 아직 이르다고 판단한다.
7. `b1`을 실행하고, 실제 price/stock 변화로 memory confidence를 업데이트한다.

#### 강한 점

Ours는 단순히 "색상을 선택하라"가 아니라, 색상 선택이 가격/재고/버튼 상태를 바꿀 수 있으니 다음 관찰에서 무엇을 다시 읽어야 하는지까지 출력한다.

## 5. 내일 보여줄 압축 표

| baseline | Flight 예시 output | Shopping 예시 output | 없는 것 |
|---|---|---|---|
| Synapse-style | retrieved trajectory 기반 `click Select` | retrieved trajectory 기반 `select black` | 후보 action별 transition |
| AWM API prototype | workflow 기반 `select organic flight` | workflow 기반 `select option -> verify price` | action별 expected delta |
| ReasoningBank-style | lesson 기반 `avoid sponsored deal -> click Select` | lesson 기반 `select option -> avoid warranty risk` | action별 expected delta |
| WMA API prototype | `a1-a4`별 predicted next state | `b1-b3`별 predicted next state | memory provenance/update |
| Ours | `a1-a4`별 expected delta/failure/verification | `b1-b3`별 expected delta/failure/verification | 구현 전에는 실제 score |

## 6. 내일 말할 핵심

```text
같은 예시를 넣었을 때 baseline마다 output 단위가 다릅니다.
Synapse는 trajectory를, AWM은 workflow를, ReasoningBank는 reasoning lesson을 출력합니다.
WMA는 action별 next state를 생성하지만, memory provenance와 update가 약합니다.
제가 보려는 것은 action별 expected transition, failure signal, verification rule을 저장하고 검색하는 memory입니다.
```
