# Web Transition Memory Hub

이 폴더는 web transition memory 연구를 한곳에 모아둔 허브다.

현재 상태는 다음과 같다.

- 논문과 GitHub를 참고해 IO 스키마와 baseline 축을 정리했다.
- 실제 실행은 `Letsur + Gemini` API 기반 프로토타입이다.
- `WMA official`, `WebDreamer local 7B`, `WebEvolver official`, `ReasoningBank full pipeline` 같은 GPU/서버 작업은 아직 별도 단계다.

## 들어있는 것

- `notes/`: baseline 선정, IO 예시, meeting brief, research plan, API audit, checklist, world-model GPU map
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

## Workspace Map

### 이 허브 안

```text
research_note/web_transition/
  README.md
  notes/
    WEB_TRANSITION_BASELINE_3X3_SELECTION.md
    WEB_TRANSITION_BASELINE_CANDIDATES.md
    WEB_TRANSITION_BASELINE_IO_EXAMPLES.md
    WEB_TRANSITION_MEMORY_MEETING_BRIEF.md
    WEB_TRANSITION_MEMORY_RESEARCH_PLAN.md
    WEB_TRANSITION_WORLD_MODEL_GPU_MAP.md
    WEB_TRANSITION_REPO_AND_API_AUDIT.md
    WEB_TRANSITION_TOMORROW_CHECKLIST.md
  baselines/
    api_transition_demo.py
    baseline_profiles.py
    transition_compare.py
    letsur_transition_demo.py
    local_transition_dry_run.py
    package_transition_results.py
    transition_viewer.py
```

### 로컬 결과물

```text
/Users/jhw/Desktop/web/hyeonwoo/eval_results/
  letsur/
    gemini-3-flash-preview/
      20260429_164258/
        taskflight_0/
        taskshopping_0/
```

### 아직 repo에 안 넣는 것

- `research_note/baselines/output/*.json` 원본 결과 파일
- `eval_results/` 전체 run tree
- GPU/server에서 돌릴 official reproduction 결과

### 참고로 같이 쓰는 기존 폴더

- `knowledge/`: 기존 Danawa/agent 작업의 지식 캐시
- `walt-tools/`: 기존 도구 자동 생성 결과

web transition 연구 자체는 `research_note/web_transition/`를 기준점으로 보면 된다.

## 비교 baseline

| baseline | 역할 | stored unit | GPU |
|---|---|---|---|
| Synapse | trajectory memory | `trajectory_exemplar` | no |
| AWM | workflow memory | `workflow` | no |
| ReasoningBank | reasoning memory | `reasoning_lesson` | no |
| WMA | text world-model prediction | `imagined_next_observation` | 8B / 24GB class |
| WebDreamer | multimodal web world model | `imagined_page_change` | 7B / 24GB class |
| RAP | planning + imagined rollout | `imagined_rollout` | 33B / 4x24GB official |

## 왜 이 조합인가

- Memory 3개는 `trajectory / workflow / lesson`을 각각 커버한다.
- WMA와 RAP는 `next state / rollout` 쪽을 커버한다.

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

기존 결과를 웹 뷰어로 다시 렌더링하려면:

```bash
python3 research_note/web_transition/baselines/transition_viewer.py eval_results/letsur/gemini-3-flash-preview/20260429_164258
```

이 명령은 각 task의 `viz_io.html`를 step-by-step 대시보드로 다시 만들고, run 루트에 `transition_viewer.html` 인덱스를 생성한다.

여러 run이나 모델 결과를 같은 task 기준으로 옆에 비교하려면:

```bash
python3 research_note/web_transition/baselines/transition_compare.py eval_results
```

이 명령은 `task_name`이 같은 결과들을 자동으로 묶어서, 왼쪽에는 task preview를, 오른쪽에는 model별 step output을 나란히 보여주는 `comparison_viewer.html`을 만든다. 상단에는 `Synapse / AWM / ReasoningBank / WMA / WebDreamer / RAP` baseline shelf도 같이 보여서, 결과와 baseline 정의, 그리고 각 baseline의 intermediate IO stage까지 한 화면에서 같이 볼 수 있다.

baseline 비교를 한 번에 보고 싶으면:

```bash
for b in synapse awm reasoningbank wma webdreamer rap; do
  python3 research_note/web_transition/baselines/letsur_transition_demo.py flight --baseline "$b"
done
```

## 서버로 넘길 작업

- `WMA official`
- `WebDreamer official`
- `WebEvolver official`
- `ReasoningBank full pipeline`
- 실제 `WebArena / BrowserGym` 재현

## 내일까지의 핵심

같은 입력에 대해 `Synapse / AWM / ReasoningBank / WMA / WebDreamer / RAP`이
무엇을 저장하고 무엇을 출력하는지 `memory_view / expected_transition / failure_signal / verification_rule`
슬롯으로 보여주는 것이다.
