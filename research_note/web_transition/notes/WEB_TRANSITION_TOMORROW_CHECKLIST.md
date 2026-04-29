# Web Transition Memory Tomorrow Checklist

작성일: 2026-04-29

## 0. 내일까지의 목표

내일까지 목표는 `구현 완료`가 아니다.

목표는 미팅에서 아래 세 가지를 말할 수 있는 상태를 만드는 것이다.

1. 어떤 문제를 풀 건지 명확히 말한다.
2. 어떤 baseline들을 봤고, 왜 이걸 고르려는지 말한다.
3. 예시 2개로 ours가 기존 방법과 뭐가 다른지 보여준다.

한 문장으로는 이렇게 말하면 된다.

> 기존 web agent memory는 주로 "무엇을 해야 하는지"를 저장했는데, 나는 "이 행동을 하면 UI가 어떻게 바뀌는지"를 저장하는 transition memory를 보려고 한다.

내일 보여줄 우리 output은 딱 3개로 고정한다.

```text
1. expected_transition: 이 action 후 무엇이 보여야 하는가
2. failure_signal: 무엇이 보이면 실패/우회/위험인가
3. verification_rule: 실행 후 무엇을 확인해야 성공으로 볼 수 있는가
```

GitHub repo와 API 실행 가능성은 `WEB_TRANSITION_REPO_AND_API_AUDIT.md`에 따로 정리했다.

## 1. 오늘 반드시 할 것

### 1. Baseline 후보 고르기

내일 미팅의 기본 baseline은 `memory style 3개 + world-model style 3개`로 보여준다.

Memory style:

| baseline | 내일 말할 역할 |
|---|---|
| Synapse-style retrieval | trajectory memory baseline |
| AWM API prototype | workflow memory baseline |
| ReasoningBank-style | reasoning memory baseline |

World-model style:

| baseline | 내일 말할 역할 |
|---|---|
| WMA API prototype / WMA official | next-state prediction baseline |
| WebDreamer | multimodal web world model baseline |
| RAP-style | runnable LLM world-model planning fallback |

따로 언급할 가까운 related work:

| related work | 이유 |
|---|---|
| R-WoM | retrieval-augmented world model이라 가깝지만 공식 코드 못 찾음 |
| DynaWeb / WebWorld | 최신 web world model 방향이지만 공식 runnable baseline으로는 불확실 |
| WebATLAS | memory + action simulation이라 매우 가깝지만 공식 코드 못 찾음 |
| ActionEngine | state-machine memory로 관련 있지만 programmatic GUI execution 쪽 |

할 일:

- `WEB_TRANSITION_BASELINE_3X3_SELECTION.md`의 표를 보고 위 조합으로 갈지 확인한다.
- 공식 코드 없는 memory 후보, SkillRL, EchoTrail-GUI, WebOperator는 내일 핵심 baseline에서 뺀다.

### 1-1. GPU 필요한 것과 아닌 것 나누기

내일 예시 2개를 같은 IO schema로 보여주는 v0에서는 local GPU가 필요하지 않다. GPU가 필요한 건 논문 official reproduction, local world model inference, fine-tuning까지 들어갈 때다.

#### GPU 없이 바로 가능한 v0

| 방법 | 실행 형태 | GPU 필요? | 내일 할 일 |
|---|---|---|---|
| Synapse-style retrieval | 작은 JSON memory + embedding/API retrieval + LLM API | 아니오 | 예시 trajectory 하나 저장하고 retrieval output 보여주기 |
| AWM API prototype | workflow memory를 수동/LLM으로 추출 후 prompt에 넣기 | 아니오 | flight/shopping workflow 한 개씩 보여주기 |
| ReasoningBank-style | success/failure lesson을 수동/LLM으로 추출 후 prompt에 넣기 | 아니오 | pitfall/strategy output 보여주기 |
| WMA API prototype | 학습된 WM 대신 LLM API에 `O_t + A_i -> delta` 묻기 | 아니오 | 후보 action별 predicted transition 생성 |
| RAP-style | LLM API로 imagined state/reward + 간단 search trace 작성 | 아니오 | world-model planning fallback으로 설명 |
| Ours | transition memory JSONL + retrieval + LLM API aggregation | 아니오 | expected transition / failure signal / verification rule 출력 |

#### GPU나 무거운 세팅이 필요한 것

| 방법 | 필요한 이유 | 내일까지 할지 |
|---|---|---|
| WMA official | Llama-3.1-8B world/value model adapter inference 또는 fine-tuning | 하지 않음. WMA API prototype으로 대체 |
| WebDreamer local 7B / official | screenshot + action imagination, vLLM/image-text inference, 24GB GPU면 직접 돌릴 수 있음 | 가능하면 넣기. 24GB GPU가 있으면 WebDreamer로 실제 예시를 하나 돌려본다 |
| WebEvolver official | co-evolving world model/agent loop, synthetic trajectory generation, 환경 세팅 | 하지 않음. paper/code review만 |
| ReasoningBank official full loop | memory extraction/evaluation pipeline을 제대로 돌리려면 API/환경 세팅이 큼 | v0는 ReasoningBank-style로 대체 |
| WebArena/BrowserGym interactive | GPU보다는 Docker/env/API 세팅과 reset/fork 비용이 큼 | 내일은 계획만 말함 |

한 줄로 말하면:

```text
내일은 GPU reproduction이 아니라, 같은 예시에서 각 baseline이 무엇을 저장하고 무엇을 출력하는지 맞추는 no-GPU IO demo를 준비하겠습니다.
```

### 2. 메인 예시 하나 고정하기

내일 메인 예시는 `Flight result page`로 고정한다.

```text
Task: Book the cheapest flight to Tokyo.
Current page: flight search results
Candidate actions:
  a1 = click Select in organic flight card
  a2 = click View Deals in ad banner
  a3 = click 1 stop filter
  a4 = click Sort by
```

내일 말할 핵심:

- Synapse/AWM/ReasoningBank는 대체로 `Select를 눌러라` 또는 `광고/우회 액션을 피하라`까지는 말할 수 있다.
- WMA는 action별 next state를 생성한다.
- Ours는 action별 expected transition뿐 아니라 `failure signal`과 `verification rule`까지 memory로 둔다.

예시 output:

```text
a1 Select -> booking modal or fare detail appears
a2 View Deals -> promo/ad detour, reject
a3 1 stop filter -> result list refresh, URL may not change
a4 Sort by -> dropdown/menu expands
```

### 3. 보조 예시 하나 준비하기

보조 예시는 `Shopping product detail`로 둔다.

```text
Task: Buy black waterproof bluetooth speaker under $30.
Current page: product detail, price $27.99, color option, warranty checkbox, Add to Cart
Candidate actions:
  a1 = select black option
  a2 = click warranty checkbox
  a3 = click Add to Cart
```

내일 말할 핵심:

- 옵션 선택 후 가격/재고가 바뀔 수 있다.
- warranty는 가격을 올려 budget 조건을 깨뜨릴 수 있다.
- Add to Cart는 cart page가 아니라 modal만 띄울 수 있다.

즉 transition memory는 task constraint verification과 연결된다.

### 4. 예시를 baseline별 입출력 단위로 보여주기

내일 핵심은 설명을 외우는 것이 아니라, 같은 예시에서 각 baseline이 무엇을 저장하고, 무엇을 입력으로 받고, 무엇을 출력하는지 단계별로 보여주는 것이다.

반드시 보여줄 축:

| baseline | 저장 단위 | inference input | inference output | 단계별 흐름 |
|---|---|---|---|---|
| Synapse-style | trajectory exemplar | task + current observation + retrieved trajectory | next action | retrieval -> prompt -> action |
| AWM API prototype | workflow | task + current observation + retrieved workflow | workflow-guided next action | workflow retrieve -> guide -> action |
| ReasoningBank-style | reasoning lesson | task + current observation + relevant success/failure lesson | pitfall + strategy + next action | lesson retrieve -> reason -> action |
| WMA API prototype | 없음 또는 world model prompt | task + O_t + candidate A_i | action별 predicted next state | candidate simulation -> action select |
| Ours | transition memory | task + O_t + candidate A_i + retrieved transition | expected delta + failure signal + verification rule | transition retrieve -> score -> verify |

상세 예시는 `WEB_TRANSITION_BASELINE_IO_EXAMPLES.md`에 정리한다.

### 5. 벤치마크 계획 말하기

내일은 이렇게 말한다.

```text
v0는 Mind2Web으로 하겠습니다.
이유는 offline action ranking을 빠르게 볼 수 있기 때문입니다.
다만 Mind2Web은 counterfactual next state가 없으므로,
candidate action별 transition은 WebArena 또는 BrowserGym에서 작은 subset으로 보겠습니다.
```

## 2. 오늘 가능하면 할 것

### 1. 5분 발표 순서 만들기

순서:

1. 문제: 웹에서 버튼을 누른 뒤 UI 변화 예측이 어렵다.
2. 기존: memory 계열은 what-to-do, world model 계열은 next-state generation.
3. Ours: external transition memory.
4. 예시: flight result page.
5. 실험: Mind2Web v0, WebArena/BrowserGym v1.
6. 피드백 요청: baseline/benchmark 선택.

### 2. 질문 답변 3개 준비

#### Q. WMA랑 뭐가 다름?

WMA는 world model을 학습해서 next observation을 생성한다. 우리는 실제 interaction transition을 external memory로 저장하고 검색한다. 그래서 업데이트와 provenance가 쉽다.

#### Q. ReasoningBank랑 뭐가 다름?

ReasoningBank는 성공/실패 trajectory에서 일반화된 reasoning lesson을 뽑는다. 우리는 lesson보다 더 낮은 단위인 `이 observation에서 이 action을 하면 어떤 UI 변화가 일어나는가`를 저장한다.

#### Q. 왜 R-WoM 대신 RAP를 넣나?

R-WoM은 web world model 관점에서는 더 가깝지만 공식 코드를 찾지 못했다. 내일은 runnable baseline을 우선하기 위해 RAP를 world-model planning fallback으로 두고, R-WoM은 최신 related work로 설명한다.

#### Q. 데이터는 어떻게 모음?

Mind2Web으로 logged transition/action ranking을 먼저 보고, candidate별 counterfactual transition은 WebArena/BrowserGym에서 같은 state를 fork 실행해 수집한다.

### 3. 숫자만 기억하기

내일 citation/star 숫자를 다 외울 필요는 없다. 아래만 기억하면 된다.

```text
AWM: cite 69, GitHub 426 stars
Synapse: cite 32, GitHub 69 stars
WMA: cite 25, GitHub 28 stars
RAP: cite 954, GitHub 192 stars
Mind2Web: cite 242, GitHub 984 stars
WebArena: cite 448, GitHub 1446 stars
BrowserGym: GitHub 1210 stars
```

## 3. 오늘 안 해도 되는 것

아래는 내일까지 하려고 하면 망한다. 하지 않아도 된다.

- 모든 baseline reproduction
- WebArena 전체 환경 세팅
- 정량 결과 만들기
- 논문 전체 related work 완성
- 블로그 포스트 작성
- SkillRL/R-WoM official reproduction까지 억지로 포함

## 4. 내일 미팅에서 받을 피드백

내일은 결론을 내려고 하지 말고, 아래 세 가지를 물어본다.

1. `transition memory` 문제정의가 충분히 중요한가?
2. baseline을 `Synapse/AWM/ReasoningBank/WMA/WebDreamer/RAP`로 잡는 게 적절한가?
3. 첫 실험을 `Mind2Web offline`으로 시작할지, 바로 `WebArena/BrowserGym interactive`로 갈지?

## 5. 내일 미팅용 최종 멘트

```text
아직 실험 결과는 없지만, 문제를 실험 가능한 형태로 내렸습니다.
기존 memory 방법은 trajectory, workflow, reasoning lesson처럼
주로 what-to-do를 저장합니다.
반면 world model 방법은 next state를 생성하지만,
학습 비용과 hallucination, provenance 문제가 있습니다.

그래서 저는 실제 웹 interaction에서 얻은
O_t + A_i => O*_{t+1} transition을 external memory로 저장하고,
후보 action별로 expected transition, failure signal, verification rule을 검색하는 방향을 보고 있습니다.
먼저 Mind2Web에서 action ranking과 logged transition을 보고,
이후 WebArena/BrowserGym에서 candidate-wise transition을 수집하려고 합니다.
```
