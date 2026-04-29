# Web Transition Memory Repo and API Audit

작성일: 2026-04-29

## 0. 결론

내일 보여줄 것은 official reproduction이 아니라 `same input -> same output schema` 비교다.

따라서 핵심은 baseline을 많이 돌리는 것이 아니라, 아래 3개를 우리 방법이 어떻게 더 잘 채우는지 보여주는 것이다.

```text
1. expected_transition
2. failure_signal
3. verification_rule
```

API key만 있으면 이 3개 예시는 GPU 없이 돌릴 수 있다. 반대로 논문 official reproduction은 대부분 환경 세팅, benchmark data, Docker, local model inference가 필요하다.

## 1. 가져온 GitHub repo

선택한 baseline repo는 모두 shallow clone으로 가져왔다.

| 방법 | local path | commit | 확인한 것 |
|---|---|---:|---|
| Synapse | `research_note/baselines/_repos/Synapse` | `08c3a25` | README, `build_memory.py`, `run_mind2web.py`, `evaluate_mind2web.py` |
| AWM | `research_note/baselines/_repos/agent-workflow-memory` | `8c0ff8c` | Mind2Web/WebArena README, `offline_induction.py`, `run_mind2web.py`, `run.py` |
| ReasoningBank | `research_note/baselines/_repos/reasoning-bank` | `ea65efd` | README, WebArena pipeline, `induce_memory.py`, `memory_management.py` |
| WMA | `research_note/baselines/_repos/WMA-Agents` | `dd89464` | README, `run_w_world_model.py`, `world_model_agent.py`, WebArena scripts |
| WebEvolver | `research_note/baselines/_repos/SelfEvolvingAgent` | `a82450e` | `WebEvolver/README.md`, world model SFT/synthesis scripts |
| RAP | `research_note/baselines/_repos/RAP` | `774817c` | README, MCTS code, run scripts |

## 2. API로 바로 보여줄 수 있는 것

아래는 official code를 그대로 돌리는 것이 아니라, 각 논문의 저장 단위와 출력 단위를 같은 예시에 맞춘 API prototype이다.

| 방법 | API로 가능한 v0 | 저장 단위 | 출력 |
|---|---|---|---|
| Synapse-style | 가능 | trajectory exemplar | next action |
| AWM API prototype | 가능 | reusable workflow | workflow-guided next action |
| ReasoningBank-style | 가능 | lesson / pitfall | strategy + next action |
| WMA API prototype | 가능 | 없음 또는 prompt world model | candidate action별 predicted transition |
| RAP-style | 가능 | search trace | imagined state/reward + selected action |
| Ours | 가능 | transition memory | expected transition + failure signal + verification rule |

## 3. Official reproduction 기준으로 무거운 것

| 방법 | repo에서 확인한 official 실행 방식 | 왜 무거운가 |
|---|---|---|
| Synapse | `python build_memory.py`, `python run_mind2web.py`, optional `finetune_mind2web.py` | Mind2Web data 필요. finetune/evaluate local model은 GPU 필요 |
| AWM | Mind2Web `offline_induction.py`, WebArena `run.py` | Mind2Web/WebArena data/env 필요. API agent 자체는 가능 |
| ReasoningBank | WebArena `pipeline_memory.py`, `induce_memory.py` | WebArena, autoeval, embedding/model client 세팅 필요 |
| WMA | `bash scripts/parallel_run_webarena_wma.sh` | WebArena Docker + world/value model adapter 또는 remote model endpoint 필요 |
| WebEvolver | Docker agent service + vLLM world model/policy model service | co-evolving loop와 SFT/synthetic trajectory pipeline이 큼 |
| RAP | LLaMA-33B 기준 4x24GB GPU 문서화 | official은 GPU heavy. 내일은 API-based search trace만 참고 |

## 4. API 사용법 메모

OpenAI는 현재 Responses API를 권장한다. Python SDK 기준 최소 형태는 다음 구조다.

```python
from openai import OpenAI

client = OpenAI()

response = client.responses.create(
    model="MODEL_NAME",
    input=[
        {
            "role": "developer",
            "content": "Return JSON only with expected_transition, failure_signal, verification_rule."
        },
        {
            "role": "user",
            "content": "TASK/O_t/candidate_actions/retrieved_memory JSON goes here."
        }
    ],
)

print(response.output_text)
```

로컬 확인:

```text
OPENAI_API_KEY: missing
Python openai package: not installed
```

즉 지금 바로 실행하려면 `OPENAI_API_KEY`와 SDK 설치가 필요하다. 키만 있으면 내일용 API prototype은 GPU 없이 가능하다.

### Letta API + Gemini 3 Flash Preview

Letta를 쓸 경우에는 stateful agent와 persistent memory block을 이용한다.

추천 모델이 `gemini-3-flash-preview`라면 Letta model handle은 provider prefix를 붙여 아래처럼 둔다.

```text
google_ai/gemini-3-flash-preview
```

실행 준비:

```bash
/tmp/web_transition_letta_venv/bin/python -m pip install letta-client
export LETTA_API_KEY=...
export LETTA_MODEL=google_ai/gemini-3-flash-preview
/tmp/web_transition_letta_venv/bin/python research_note/baselines/letta_transition_demo.py flight
/tmp/web_transition_letta_venv/bin/python research_note/baselines/letta_transition_demo.py shopping
```

현재 로컬에서는 Homebrew Python이 system install을 막기 때문에 `/tmp/web_transition_letta_venv`에 `letta-client`를 설치해 두었다.

Letta agent에는 memory block 3개를 넣는다.

| block | 내용 |
|---|---|
| `persona` | web transition evaluator 역할 |
| `io_protocol` | `expected_transition`, `failure_signal`, `verification_rule`만 출력하라는 규칙 |
| `transition_memory` | flight/shopping 예시에 대한 transition memory |

### Letsur API + Gemini 3 Flash Preview

실제 사용 API는 Letta가 아니라 Letsur였다. Letsur는 OpenAI-compatible `chat.completions` gateway다.

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://gateway.letsur.ai/v1",
    api_key="YOUR_API_KEY",
)

response = client.chat.completions.create(
    model="gemini-3-flash-preview",
    messages=[
        {"role": "system", "content": "Return JSON only."},
        {"role": "user", "content": "..."}
    ],
)
```

이번에 실제 호출 성공한 명령:

```bash
export LETSUR_API_KEY=...
export LETSUR_MODEL=gemini-3-flash-preview
/tmp/web_transition_letta_venv/bin/python research_note/baselines/letsur_transition_demo.py flight
/tmp/web_transition_letta_venv/bin/python research_note/baselines/letsur_transition_demo.py shopping
```

생성해둔 Letsur 결과:

```text
research_note/baselines/output/flight_letsur.json
research_note/baselines/output/shopping_letsur.json
```

두 결과 모두 valid JSON이고, schema는 아래로 통일했다.

```json
{
  "candidate_evaluations": [
    {
      "id": "...",
      "expected_transition": "...",
      "failure_signal": "...",
      "verification_rule": "..."
    }
  ],
  "selected_action": "...",
  "selection_reason": "..."
}
```

## 5. 내일 보여줄 최소 비교

Flight와 Shopping 예시 각각에 대해 아래 같은 JSON을 만들면 된다.

```json
{
  "method": "Ours",
  "input": {
    "task": "...",
    "observation": "O_t",
    "candidate_actions": ["A_1", "A_2", "A_3"],
    "retrieved_memory": ["..."]
  },
  "output": {
    "predicted_transition_by_action": {
      "A_1": {
        "expected_transition": "...",
        "failure_signal": "...",
        "verification_rule": "..."
      }
    },
    "selected_action": "A_1"
  }
}
```

키 없이 확인하는 dry-run 결과:

```bash
python3 research_note/baselines/local_transition_dry_run.py flight
python3 research_note/baselines/local_transition_dry_run.py shopping
```

생성해둔 출력 파일:

```text
research_note/baselines/output/flight_dry_run.json
research_note/baselines/output/shopping_dry_run.json
```

여기서 baseline은 같은 input을 받되, 못 채우는 칸을 명확히 빈칸으로 둔다.

```json
{
  "method": "AWM API prototype",
  "output": {
    "workflow_guidance": "...",
    "selected_action": "A_1",
    "missing_output": [
      "candidate-wise expected_transition",
      "failure_signal",
      "verification_rule"
    ]
  }
}
```
