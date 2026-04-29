# Web Transition World-Model GPU Map

작성일: 2026-04-29

이 문서는 `WMA / WebDreamer / RAP`를 기준으로, 우리 작업에서 어떤 역할을 맡기고 어떤 GPU가 필요한지 한 번에 보이도록 정리한 메모다.

## 한 줄 결론

24GB GPU 1장만 있으면, **가장 현실적인 web-native world-model baseline은 WebDreamer-7B**다.  
`WMA`는 가장 정면으로 `transition`을 예측하는 텍스트 중심 baseline이고, `RAP`는 planning/search의 근본 baseline이지만 공식 세팅은 무겁다.

## 비교표

| 방법 | 공개 모델 / 구조 | 우리 입력 | 우리 출력 | 연구 역할 | GPU 감 |
|---|---|---|---|---|---|
| WMA | `Meta-Llama-3.1-8B` world/value adapters | text observation + candidate actions | next observation delta / transition description | `O_t + A_i -> O*_{t+1}`를 가장 정면으로 예측하는 text world model | 24GB 1장에서도 시작 가능 |
| WebDreamer | `Dreamer-7B` (`Qwen2-VL-7B` base, 8B params) | screenshot + task + action | imagined page change, accessibility tree, html | 가장 web-native한 multimodal world model baseline | 24GB 1장 가능, 48GB면 훨씬 편함 |
| RAP | `LLaMA-33B` | state + candidate actions | imagined state / reward / search trace | planning/search의 근본 baseline | 공식 README 기준 4x24GB |

## 무엇이 다른가

### WMA

- 웹 상태를 텍스트/구조화된 transition으로 압축해서 다룬다.
- 우리가 만들 `transition memory`와 가장 직접적으로 맞닿아 있다.
- 장점은 비교가 선명하다는 점이고, 한계는 screenshot-level imagination이 아니라는 점이다.

### WebDreamer

- screenshot을 입력으로 받아서, “이 action을 하면 페이지가 어떻게 바뀔지”를 시뮬레이션한다.
- `change description`, `a11y tree`, `html`처럼 여러 포맷의 미래 페이지를 예측한다.
- 우리 주제에서 가장 자연스러운 `web world model` 후보 중 하나다.

### RAP

- LLM을 world model처럼 써서 rollout / reward / search trace를 만든다.
- web-specific이라기보다는 planning 측면의 근본 비교축이다.
- 공식 세팅은 무거워서, 내일 데모보다는 서버 실험용에 가깝다.

## 추천 배치

| 장비 | 추천 |
|---|---|
| 24GB 1장 | `WebDreamer-7B` 우선, `WMA`는 API prototype 또는 가벼운 inference |
| 24GB 2장 | `WMA`와 `WebDreamer-7B`를 더 넉넉하게 비교 가능 |
| 4x24GB 이상 | `RAP` 공식 재현권 |
| 서버 | `WebEvolver` / `RAP` / full reproduction |

## 공식 링크

- [WMA repo](https://github.com/kyle8581/WMA-Agents)
- [WebDreamer repo](https://github.com/OSU-NLP-Group/WebDreamer)
- [WebDreamer paper](https://arxiv.org/abs/2411.06559)
- [Dreamer-7B model card](https://huggingface.co/osunlp/Dreamer-7B)
- [RAP repo](https://github.com/Ber666/RAP)
- [RAP paper](https://arxiv.org/abs/2305.14992)
