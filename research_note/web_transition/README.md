# Web Transition Memory Hub

이 폴더는 web transition memory 연구를 한곳에 모아둔 허브다.

현재 상태는 다음과 같다.

- 논문과 GitHub를 참고해 IO 스키마와 baseline 축을 정리했다.
- 실제 실행은 `Letsur + Gemini` API 기반 프로토타입이다.
- `WMA official`, `WebEvolver official`, `ReasoningBank full pipeline` 같은 GPU/서버 작업은 아직 별도 단계다.

## 들어있는 것

- `baselines/`: baseline comparison용 실행 스크립트
- `README.md`: 전체 상태 요약

## 저장 경로 규칙

로컬 실행 결과는 기본적으로 아래 형태로 저장한다.

```text
eval_results/<provider>/<model>/<run_id>/<baseline>/task<example>_0/
```

task 폴더에는 보통 아래가 들어간다.

- `result.json`
- `metadata.json`
- `interact_messages.json`
- `system_prompt.txt`
- `user_prompt.txt`
- `assistant_output.txt`
- `viz_io.html`
- `S1/`, `S2/`, ...

## 비교 baseline

| baseline | 역할 | stored unit | GPU |
|---|---|---|---|
| Synapse | trajectory memory | `trajectory_exemplar` | no |
| AWM | workflow memory | `workflow` | no |
| ReasoningBank | reasoning memory | `reasoning_lesson` | no |
| WMA | world-model style prediction | `imagined_next_observation` | server/offical |
| RAP | planning + imagined rollout | `imagined_rollout` | no for API demo, yes for full official style |
| Ours | transition memory | `transition_memory` | no |

## 왜 이 조합인가

- Memory 3개는 `trajectory / workflow / lesson`을 각각 커버한다.
- WMA와 RAP는 `next state / rollout` 쪽을 커버한다.
- Ours는 `expected_transition / failure_signal / verification_rule`을 직접 저장한다.

## 실행 예시

```bash
python3 research_note/web_transition/baselines/local_transition_dry_run.py flight
python3 research_note/web_transition/baselines/local_transition_dry_run.py shopping
```

API가 있으면:

```bash
export LETSUR_API_KEY=...
export LETSUR_MODEL=gemini-3-flash-preview
python3 research_note/web_transition/baselines/letsur_transition_demo.py flight --baseline ours
```

baseline 비교를 한 번에 보고 싶으면:

```bash
for b in synapse awm reasoningbank wma rap ours; do
  python3 research_note/web_transition/baselines/letsur_transition_demo.py flight --baseline "$b"
done
```

## 서버로 넘길 작업

- `WMA official`
- `WebEvolver official`
- `ReasoningBank full pipeline`
- 실제 `WebArena / BrowserGym` 재현

## 내일까지의 핵심

같은 입력에 대해 `Synapse / AWM / ReasoningBank / WMA / RAP / Ours`가
무엇을 저장하고 무엇을 출력하는지 `memory_view / expected_transition / failure_signal / verification_rule`
슬롯으로 보여주는 것이다.

