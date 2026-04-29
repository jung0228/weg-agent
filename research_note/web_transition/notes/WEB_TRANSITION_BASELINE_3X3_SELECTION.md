# Web Transition Memory 3x3 Baseline Selection

작성일: 2026-04-29

목표: 내일 미팅에서 baseline을 `memory style 3개`와 `world-model style 3개`로 깔끔하게 보여준다. 기준은 다음 네 가지다.

1. 우리 문제와 얼마나 가까운가?
2. 근본/대표 논문인가, 아니면 최신 논문인가?
3. citation이 어느 정도 있는가?
4. GitHub가 있어 실제로 돌려볼 수 있는가?

Citation은 빠른 비교용으로 arXiv.gg 기준을 우선 사용했고, RAP만 Semantic Scholar 기준을 병기했다. GitHub stars/forks는 GitHub API로 확인했다. 숫자는 2026-04-29 기준이며 DB마다 달라질 수 있다.

## 1. 최종 추천 3x3

### Memory-Style Baselines

| 순위 | 방법 | 연도/venue | cite | GitHub | stars / forks | 선정 이유 | 내일 포지션 |
|---:|---|---|---:|---|---:|---|---|
| 1 | AWM: Agent Workflow Memory | 2024/2025 | 69 | [zorazrw/agent-workflow-memory](https://github.com/zorazrw/agent-workflow-memory) | 426 / 50 | 웹 에이전트 memory에서 workflow abstraction의 대표. 코드도 있고 Mind2Web/WebArena 모두 연결됨. | workflow memory baseline |
| 2 | Synapse | ICLR 2024 | 32 | [ltzheng/Synapse](https://github.com/ltzheng/Synapse) | 69 / 12 | trajectory-as-exemplar + memory의 근본 baseline. raw trajectory memory와 비교하기 좋음. | trajectory memory baseline |
| 3 | ReasoningBank | ICLR 2026 | 2 | [google-research/reasoning-bank](https://github.com/google-research/reasoning-bank) | 247 / 25 | 최신 memory framework. 성공/실패 trajectory를 reasoning strategy로 distill하고 WebArena/Mind2Web 코드가 있음. | reasoning memory baseline |

### World-Model / Action-Simulation Baselines

| 순위 | 방법 | 연도/venue | cite | GitHub | stars / forks | 선정 이유 | 내일 포지션 |
|---:|---|---|---:|---|---:|---|---|
| 1 | WMA: Web Agents with World Models | ICLR 2025 | 25 | [kyle8581/WMA-Agents](https://github.com/kyle8581/WMA-Agents) | 28 / 2 | `O_t, A_i -> next observation delta`를 직접 예측하는 가장 정면 baseline. | learned world model baseline |
| 2 | WebEvolver | EMNLP 2025 | 6 | [Tencent/SelfEvolvingAgent](https://github.com/Tencent/SelfEvolvingAgent) | 100 / 5 | co-evolving world model이 synthetic trajectory 생성과 inference look-ahead에 쓰임. 최신이고 코드 있음. | co-evolving world model baseline |
| 3 | RAP: Reasoning via Planning | EMNLP 2023 | 954* | [Ber666/RAP](https://github.com/Ber666/RAP) | 192 / 23 | LLM을 world model + agent로 쓰는 근본 planning baseline. web-specific은 아니지만 코드가 있고 같은 `state + action -> imagined state/reward` IO로 맞출 수 있음. | runnable world-model planning fallback |

*RAP citation은 Semantic Scholar 기준이다.

## 2. 왜 이 조합인가

### Memory 3개가 커버하는 축

| 방법 | 저장 단위 | 같은 input에서 나오는 output | 우리와 비교할 포인트 |
|---|---|---|---|
| Synapse | full trajectory exemplar | retrieved trajectory 기반 next action | raw trajectory는 정보가 풍부하지만 사이트/순서/ID에 묶임 |
| AWM | reusable workflow | workflow guidance 기반 next action | workflow는 절차를 주지만 action별 UI 변화는 직접 예측하지 않음 |
| ReasoningBank | reasoning strategy / lesson | relevant memory item, pitfall, strategy | 성공/실패에서 배운 교훈은 주지만 concrete transition memory는 아님 |

### World-model 3개가 커버하는 축

| 방법 | world model 사용 방식 | 같은 input에서 나오는 output | 우리와 비교할 포인트 |
|---|---|---|---|
| WMA | trained world model | candidate action별 predicted next observation | 우리와 가장 정면 비교. 단, 지식은 parameter 안에 있음 |
| WebEvolver | co-evolving world model | synthetic trajectory / look-ahead simulation | self-improvement와 world model을 함께 키움 |
| RAP | LLM-as-world-model + MCTS | imagined next state, reward, search trace | web-specific은 아니지만 runnable하고 world-model planning의 근본 비교축을 줌 |

## 3. 코드 없는 최신 web-world-model 논문은 어떻게 둘까

web-agent world-model 계열에서 공식 코드가 확실한 것은 현재 확인 기준으로 WMA와 WebEvolver가 가장 강하다. 최신 논문들은 우리와 가깝지만 코드가 없어 내일 핵심 baseline에는 넣지 않는다.

paper-level related work로 둘 후보:

| 방법 | cite | GitHub | 이유 |
|---|---:|---|---|
| R-WoM | 0 | 공식 repo 못 찾음 | retrieval로 world model hallucination을 줄이는 최신 논문. 우리 external memory 방향과 비교하기 좋음 |
| DynaWeb | 0 | 공식 repo 못 찾음 | web world model로 imagined rollout을 만들어 model-based RL을 하는 최신 2026 논문 |
| WebWorld | 0 | 공개 repo 확인 실패 | 대규모 web simulator/world model 방향. 최신성이 좋지만 바로 돌릴 baseline으로는 불확실 |
| WebATLAS | 0 | 공식 repo 못 찾음 | memory + action simulation이라 매우 가깝지만 코드가 없어 paper-level 비교에 둠 |

R-WoM류를 꼭 넣고 싶으면 v0에서는 `WMA API prototype + retrieved tutorial/memory context` 형태의 API prototype으로 구현한다. 단, 이 경우 official reproduction baseline은 아니다.

## 4. 실행 계획 기준 baseline

### 내일까지 보여줄 baseline 표

```text
Memory:
  1. Synapse-style retrieval
  2. AWM API prototype
  3. ReasoningBank-style reasoning memory

World model:
  1. WMA API prototype / WMA official
  2. WebEvolver paper/code review
  3. RAP-style LLM world-model planning

Ours:
  Transition memory
```

### 실제 구현 순서

| 순서 | 구현 | 이유 |
|---:|---|---|
| 1 | Synapse-style retrieval | 가장 쉬운 retrieval baseline |
| 2 | AWM API prototype | workflow induction prompt만 만들면 됨 |
| 3 | WMA API prototype | world model fine-tuning 없이 바로 비교 가능 |
| 4 | Ours transition memory | 핵심 비교 대상 |
| 5 | ReasoningBank-style memory | 코드 참고 가능하지만 extraction/evaluation loop가 조금 큼 |
| 6 | WMA official / WebEvolver official | 세팅과 비용 확인 필요 |
| 7 | RAP-style search | web-specific adapter를 만들어야 해서 뒤로 |

## 5. GPU / 실행 부담 기준

내일 회의용 예시 2개는 official reproduction이 아니라 common IO demo다. 따라서 local GPU 없이도 충분히 보여줄 수 있다.

### No-GPU v0로 가능한 것

| 방법 | v0 실행 방식 | GPU 필요? | 비고 |
|---|---|---|---|
| Synapse-style | 저장된 trajectory exemplar를 retrieve해서 prompt에 넣음 | 아니오 | embedding도 API나 lightweight local로 처리 가능 |
| AWM API prototype | trajectory에서 workflow를 추출해 memory로 저장하고 retrieve | 아니오 | workflow extraction은 LLM API로 충분 |
| ReasoningBank-style | 성공/실패에서 lesson/pitfall을 추출해 retrieve | 아니오 | official full loop가 아니라 IO demo 기준 |
| WMA API prototype | LLM API가 candidate action별 next-state delta를 생성 | 아니오 | WMA official 대신 쓰는 빠른 baseline |
| RAP-style | LLM API로 imagined state/reward와 search trace를 생성 | 아니오 | web adapter는 단순 prompt로 시작 |
| Ours | transition memory JSONL을 retrieve해서 expected transition/failure signal/verification rule 생성 | 아니오 | 내일 보여줄 핵심 |

### GPU 또는 heavy setup이 필요한 것

| 방법 | 왜 무거운가 | 내일 처리 |
|---|---|---|
| WMA official | Llama-3.1-8B world/value model adapter inference, fine-tuning, WebArena setup | `WMA API prototype`으로 대체하고 official은 후순위 |
| WebEvolver official | co-evolving world model/agent loop와 synthetic trajectory generation | paper/code review만 |
| ReasoningBank official | full memory extraction/eval pipeline과 benchmark setup | `ReasoningBank-style` prompt baseline으로 대체 |
| WebArena/BrowserGym interactive | GPU보다 Docker/env/API/reset-fork 비용이 큼 | v1 계획으로만 둠 |

## 6. 제외/backup 후보

| 방법 | cite | GitHub | stars / forks | 왜 backup인가 |
|---|---:|---|---:|---|
| WebATLAS | 0 | 공식 repo 못 찾음 | - | memory + action simulation이라 매우 가까움. 코드가 없어 paper-level related work로 적합 |
| ActionEngine | 0 | 공식 repo 못 찾음 | - | state-machine memory가 가깝지만 web transition memory보다는 programmatic GUI execution에 가까움 |
| WAC | 0 | 공식 repo 못 찾음 | - | action correction에는 관련 있지만 memory baseline은 아님 |
| R-WoM | 0 | 공식 repo 못 찾음 | - | 최신 web-world-model 방향은 좋지만 내일 실행 baseline으로는 불확실 |

## 7. 미팅에서 말할 한 줄 결론

```text
Baseline은 memory 계열 3개와 world-model 계열 3개로 나누겠습니다.
Memory 쪽은 Synapse, AWM, ReasoningBank로 trajectory/workflow/reasoning memory를 커버하고,
world-model 쪽은 WMA, WebEvolver, RAP로 web next-state prediction, co-evolving WM, 근본 LLM world-model planning을 커버하겠습니다.
R-WoM/WebATLAS/DynaWeb/WebWorld는 우리와 가까운 최신 related work지만 공식 코드가 확인되지 않아 paper-level로만 비교하겠습니다.
```

## 8. 출처

- [Synapse arXiv](https://arxiv.org/abs/2306.07863), [Synapse GitHub](https://github.com/ltzheng/Synapse)
- [Agent Workflow Memory arXiv](https://arxiv.org/abs/2409.07429), [AWM GitHub](https://github.com/zorazrw/agent-workflow-memory)
- [ReasoningBank arXiv](https://arxiv.org/abs/2509.25140), [ReasoningBank GitHub](https://github.com/google-research/reasoning-bank)
- [WMA arXiv](https://arxiv.org/abs/2410.13232), [WMA OpenReview](https://openreview.net/forum?id=moWiYJuSGF), [WMA GitHub](https://github.com/kyle8581/WMA-Agents)
- [WebEvolver ACL Anthology](https://aclanthology.org/2025.emnlp-main.454/), [WebEvolver arXiv](https://arxiv.org/abs/2504.21024), [Tencent/SelfEvolvingAgent GitHub](https://github.com/Tencent/SelfEvolvingAgent)
- [RAP arXiv](https://arxiv.org/abs/2305.14992), [RAP GitHub](https://github.com/Ber666/RAP)
- [R-WoM arXiv](https://arxiv.org/abs/2510.11892), [R-WoM OpenReview](https://openreview.net/forum?id=5ZaoXB3MdP)
- [DynaWeb arXiv](https://arxiv.org/abs/2601.22149)
- [WebWorld arXiv](https://arxiv.org/abs/2602.14721)
- [WebATLAS arXiv](https://arxiv.org/abs/2510.22732)
- [ActionEngine arXiv](https://arxiv.org/abs/2602.20502)
