# Web Transition Memory Baseline Candidates

작성일: 2026-04-29

이 문서는 내일 미팅용 baseline 후보의 짧은 요약이다. 상세 표, citation, GitHub stars/forks, 선정 이유는 `WEB_TRANSITION_BASELINE_3X3_SELECTION.md`를 기준으로 본다.

## 최종 기준

내일 핵심 baseline은 `공식 코드가 있거나 즉시 구현 가능한 방법`만 우선한다.

따라서 공식 repo를 확인하지 못한 후보는 핵심 baseline에서 제외하고, 필요하면 related work로만 언급한다.

## Memory-Style 3개

| 방법 | 역할 | GitHub | 선정 이유 |
|---|---|---|---|
| Synapse | trajectory memory baseline | [ltzheng/Synapse](https://github.com/ltzheng/Synapse) | 과거 trajectory retrieval의 대표 baseline |
| AWM | workflow memory baseline | [zorazrw/agent-workflow-memory](https://github.com/zorazrw/agent-workflow-memory) | web agent workflow abstraction의 대표 baseline |
| ReasoningBank | reasoning memory baseline | [google-research/reasoning-bank](https://github.com/google-research/reasoning-bank) | 성공/실패 trajectory에서 reasoning lesson을 만드는 최신 memory baseline |

## World-Model / Action-Simulation 3개

| 방법 | 역할 | GitHub | 선정 이유 |
|---|---|---|---|
| WMA | learned web world model baseline | [kyle8581/WMA-Agents](https://github.com/kyle8581/WMA-Agents) | `O_t + A_i -> O*_{t+1}`를 가장 정면으로 다룸 |
| WebEvolver | co-evolving world model baseline | [Tencent/SelfEvolvingAgent](https://github.com/Tencent/SelfEvolvingAgent) | world model을 synthetic trajectory와 look-ahead에 같이 사용 |
| RAP | runnable world-model planning fallback | [Ber666/RAP](https://github.com/Ber666/RAP) | web-specific은 아니지만 LLM-as-world-model + planning의 근본 baseline |

## Paper-Level Related Work

| 방법 | 이유 |
|---|---|
| R-WoM | retrieval-augmented world model이라 우리 방향과 가깝지만 공식 repo를 찾지 못함 |
| DynaWeb | 2026 web world model + model-based RL 방향. 공식 runnable repo를 찾지 못함 |
| WebWorld | 2026 대규모 web simulator/world model 방향. 공개 repo 확인이 불확실함 |
| WebATLAS | memory + action simulation이라 가깝지만 공식 repo를 찾지 못함 |
| ActionEngine | state-machine memory와 관련 있지만 web transition memory보다는 programmatic GUI execution 쪽 |

## 내일 말할 요약

```text
Memory baseline은 Synapse, AWM, ReasoningBank로 trajectory/workflow/reasoning lesson을 커버하고,
world-model baseline은 WMA, WebEvolver, RAP로 next-state prediction, co-evolving WM, runnable world-model planning을 커버하겠습니다.
공식 코드가 없는 최신 논문들은 core baseline이 아니라 related work로만 두겠습니다.
```
