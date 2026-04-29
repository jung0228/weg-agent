# weg-agent

다나와 PC 견적 자동화 + WebVoyager 스타일 평가 파이프라인.
**Planner-Executor + browser-use + WALT Tool Discovery + Eval (Booking / KTX)**

---

## 최신 구조 (v2 — browser-use 기반)

```
main_bu.py                  ← browser-use 기반 에이전트 (권장)
├─ browser-use Agent        ← DOM 인덱싱 기반 (좌표 클릭 X)
│    AgentBrain: evaluation_previous_goal + memory + next_goal + plan_update + action
│    Loop Detection: 동일 액션 5/8/12회 반복 시 자동 nudge
├─ tools_bu.py              ← Danawa 전용 커스텀 툴 (browser-use BUPage 어댑터)
│    add_product / get_products / select_category / filter / sort_cheapest 등
└─ executor.py              ← add_product 성공 시 즉시 auto-DONE (무한루프 방지)

3가지 비교 모드:
  python main_bu.py --task office_50                  # 툴O + 구조설명O (기본)
  python main_bu.py --task office_50 --no-context     # 툴O + 구조설명X
  python main_bu.py --task office_50 --no-tools       # 툴X (browser-use 기본만)
```

---

## 평가 파이프라인

### Booking.com 평가 (WebVoyager 방식)

```bash
# 에이전트 실행 (기본 10개 샘플)
python eval_booking_run.py
python eval_booking_run.py --n 2              # 2개만
python eval_booking_run.py --task_ids Booking--0,Booking--3

# LLM-as-Judge (GPT-4V → 스크린샷 + 답변 보고 SUCCESS/NOT SUCCESS 판정)
python eval_booking_judge.py \
  --result_dir eval_results/<dir_name> \
  --model gemini-3-flash-preview \
  --base_url https://gateway.letsur.ai/v1 \
  --api_key <LETSUR_API_KEY>
```

**평가 흐름**:
1. 에이전트 실행 → 매 스텝 스크린샷 저장 → `done` 액션으로 최종 답변
2. Judge: 마지막 스크린샷 3장 + 태스크 + 답변 → GPT-4V 판정
3. 스크린샷이 진실 (답변 ≠ 스크린샷이면 스크린샷 우선)

### KTX / ITX / 무궁화호 평가 (Korail)

```bash
python eval_korail_run.py                          # 기본 3개 태스크
python eval_korail_run.py --task_ids ktx_0         # 특정 태스크만

# dry_run 모드 (기본): 결제 직전 스크린샷 + 중단
# --purchase 플래그: 실제 예매 (실제 돈 나감 — 주의)
```

**태스크 형식** (WebVoyager 자연어 스타일):
```
"수원에서 부산으로 가는 2026년 4월 10일 KTX 승차권을 예매하고
 열차 번호, 출발/도착 시각을 알려주세요."
```

---

## WALT Tool Discovery

### Danawa 자동 탐색

```bash
OPENAI_API_KEY=<letsur_key> \
OPENAI_BASE_URL=https://gateway.letsur.ai/v1 \
walt discover --url https://shop.danawa.com/virtualestimate/ \
  --output ./walt-tools/danawa \
  --llm gemini-3-flash-preview \
  --planner-llm gemini-3-flash-preview
```

**생성된 툴** (`walt-tools/danawa/`):

| 툴 | 설명 |
|----|------|
| `search_pc_components` | 키워드/카테고리/스펙 필터로 부품 검색 |
| `manage_estimate_cart` | 견적 담기, 호환성 체크, 저장/공유 |
| `search_assembly_gallery` | 완성 빌드 갤러리 검색 |
| `search_purchase_reviews` | 구매 후기 검색/필터 |
| `filter_community_forum` | 하드웨어 카테고리별 포럼 필터 |
| `post_pc_consultation` | PC 구매 상담 글쓰기 |
| `browse_events` | 이벤트/프로모션 탐색 |

**WALT 동작 원리**:
1. **Stage 1**: browser-use 에이전트가 실제로 사이트 탐색 (카테고리 클릭, 필터 확인 등)
2. **Stage 2**: 탐색 결과로 API 스펙 JSON 설계
3. **Stage 3**: 각 툴을 에이전트가 직접 실연(demonstration) → Selector 기록 → `tool.json` 생성
4. 이후 실행은 **결정론적** (저장된 Selector 재사용, 매번 LLM 추론 불필요)

---

---

## 전체 구조

```
태스크 (예산 + 목적)
    │
    ▼
[agent.py] 오케스트레이터
    │
    ├─ 0. [ui_explorer.py] UI 탐색 (선택적, --explore-ui)
    │       다나와 페이지 직접 조작 → 클릭/스크롤 시 상태 변화 기록
    │       → [knowledge.py] DanawaKnowledge 캐싱 (knowledge/danawa_ui.json)
    │
    ├─ 1. [planner.py] 계획 수립 (LLM 1회 호출)
    │       태스크 + 예산 → PlanStep 리스트
    │       {"name": "CPU 선택", "budget": 80000, "hint": "Pentium Gold G7400"}
    │
    ├─ 2. [executor.py] × N단계 반복
    │       각 서브태스크를 AgentBrain 미니 ReAct로 실행
    │       │
    │       ├─ [som.py] perceive(page)
    │       │    스크린샷만 캡처 (DOM 수집 없음)
    │       │    → ScreenState(screenshot_b64, url, w, h)
    │       │
    │       ├─ LLM Vision (AgentBrain 5-field 출력)
    │       │    Eval:    이전 액션 결과 평가 (Success/Failed/N/A)
    │       │    Memory:  이 스텝에서 기억할 정보
    │       │    Predict: 다음 액션 실행 시 예상 결과
    │       │    Goal:    다음 액션 의도 한 줄
    │       │    Action:  TOOL ... / CLICK (x,y) / DONE ...
    │       │
    │       ├─ [tools.py] TOOL 명령 → DOM 직접 실행 (신뢰성↑)
    │       │    select_category / filter / search / sort_cheapest
    │       │    get_products / add_product (광고 자동 스킵)
    │       │    remove_part / get_cart / clear_filters
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

| | v1 | v2 | v3 | v4 | v5 | v6 (현재) |
|---|---|---|---|---|---|---|
| **구조** | 단일 flat ReAct | Planner-Executor | + WALT Tools | + Knowledge Base + Filter TOOL | + sort 분리 + 중고 제외 | + DOM 셀렉터 수정 |
| **인식** | SoM (DOM+오버레이) | Adaptive SoM | Pure Vision | Pure Vision | Pure Vision | Pure Vision |
| **액션** | `CLICK [N]` DOM ID | `CLICK [N]` DOM ID | `TOOL` + `CLICK (x,y)` | + `TOOL filter` | + `--no-step-budget` | 동일 |
| **담기 문제** | 실패 | 실패 | DOM .click() 해결 | 동일 | 중고 제품 자동 제외 | 중고 fallback 완전 제거 |
| **광고 스킵** | 없음 | 없음 | recom_area 필터 | 동일 | 동일 | 동일 |
| **검색 방식** | 없음 | 좌표 클릭 | 검색창 Enter | btn_search + 탭 자동 선택 | search 후 sort 금지 | 메모리 방법 A 명시 |
| **필터** | 없음 | 없음 | 없음 | 체크박스 DOM 클릭 | 카테고리 뷰 전용 | 동일 |
| **정렬** | 없음 | 없음 | 없음 | onclick-ASC | onclick-ASC (카테고리 뷰만) | 동일 |
| **제품명/가격** | 없음 | 없음 | 없음 | 없음 | 잘못된 셀렉터 (항상 실패) | 실제 DOM 기반 수정 |
| **LLM 출력** | `Thought/Action` | `Eval/Memory/Goal/Action` | + `Predict:` | 동일 | + 빈 Action DONE 힌트 | 동일 |

---

## 에러 기록 & 해결 과정

### 1. "담기" 버튼 좌표 클릭 실패
**증상**: `CLICK (x, y)`로 담기 버튼을 눌러도 아무 반응 없음. 같은 좌표 3~5회 반복.

**원인 분석**: 브라우저 DevTools로 DOM 확인 →
`<a class="btn_choice2 wishAction">` 는 jQuery `.on('click', ...)` 이벤트 리스너가 걸린 앵커 태그.
Playwright `page.mouse.click(x, y)`는 합성 마우스 이벤트를 발생시키는데, 이 경우 jQuery 리스너가 트리거되지 않는 케이스 존재.
또한 SoM의 `filter_for_goal`이 "담기" 텍스트 버튼을 goal 키워드와 관련 없다고 점수 0으로 제외 → LLM이 엉뚱한 ID로 hallucination.

**해결**: `TOOL add_product N` — JS `element.click()`으로 jQuery 리스너 직접 트리거.

---

### 2. 광고 제품이 목록 1번으로 잡힘
**증상**: `TOOL add_product 1` 실행 시 69만원짜리 고급 CPU가 담김. 최저가 선택 목적이 무산.

**원인**: 다나와 PC견적 제품 목록 상단 2~3개는 `tr.recom_area` 클래스를 가진 광고/추천 제품.
`sort_cheapest` 후에도 광고 행은 순서 고정.

**해결**: `_JS_GET_PRODUCTS`와 `_JS_ADD_PRODUCT` 모두 `!tr.classList.contains('recom_area')` 필터 추가.
광고는 번호 카운트에서 완전 제외 → 1번 = 비광고 최저가 보장.

---

### 3. 잘못된 URL로 탐색
**증상**: `ui_explorer.py` 실행 시 오른쪽 패널 카테고리 버튼을 전혀 인식 못 함. 클릭해도 반응 없음.

**원인**: `DANAWA_ESTIMATE_URL = "https://prod.danawa.com/info/?pcode=22166839"`
→ 다나와 **상품 상세 페이지** (특정 SSD 상품 페이지)로 이동하고 있었음.
PC 견적 도구 URL은 `https://shop.danawa.com/virtualestimate/` 임.

**해결**: URL 수정. 동시에 `knowledge.py`의 BASE_KNOWLEDGE URL도 수정.

---

### 4. 카테고리 셀렉터 불일치
**증상**: `TOOL select_category "CPU"` 실행 시 "카테고리 'CPU' 못 찾음" 에러.

**원인**: `tools.py`가 `.estimate_category li`, `.pc_main_wrap li` 등을 사용했으나 실제 DOM은 달랐음.
브라우저에서 직접 확인한 실제 구조:
```html
<dd class="category_873 select pd_item">
  <a class="pd_item_title" onclick="category(873,2);return false;">CPU</a>
</dd>
```
카테고리 버튼은 `dd[class*="category_"].pd_item > a.pd_item_title` 이고,
클릭 방식은 `category(ID, 2)` JS 전역 함수 호출.

**해결**: 카테고리명 → ID 매핑 테이블 추가 후 `category(ID, 2)` 직접 호출.
```javascript
const NAME_TO_ID = { 'CPU': 873, '메인보드': 875, 'SSD': 32617, ... }
if (typeof category === 'function') category(catId, 2);
```

---

### 5. 검색이 전체 사이트 검색으로 이탈
**증상**: `TOOL search "H410M"` 실행 후 결과가 `전체(114) / 메인보드(1) / 케이스(113)` 으로 분리됨.
메인보드 카테고리에서 검색했는데 케이스 결과 113개가 섞여 표시.

**원인**: `page.keyboard.press("Enter")` 가 `#searchProduct` (카테고리 내 검색창)가 아닌
상단 글로벌 검색창(`#gnbSearchKeyword`)을 트리거하여 전체 사이트 검색 수행.

**해결 1**: Enter 제거 → `button.btn_search` DOM 클릭으로 변경.
**해결 2**: 검색 후 `input[name="serviceSectionSeq"]` 라디오 버튼이 나타나면
현재 선택된 카테고리(오른쪽 패널의 `dd.select`)와 일치하는 탭 자동 클릭.

---

### 6. 플래너가 예산 초과 모델을 추천
**증상**: 50만원 사무용 빌드에서 CPU 예산 95,000원으로 할당했는데 플래너가 `hint: "i3-12100"` 생성.
에이전트가 i3-12100(실제 시세 ~150,000원)을 검색 → 예산 초과 확인 → 스스로 G6900으로 재검색 → 워크플로우 꼬임.

**원인**: 플래너 프롬프트에 "Celeron G6900, i3-12100F" 를 나열만 했고 실제 가격 정보가 없음.
LLM이 "i3-12100이 더 좋은 CPU"라는 사전 지식으로 추천.

**해결**: 플래너 프롬프트에 실제 시세표 추가.
```
| CPU | Celeron G6900    | 60,000~75,000원  | LGA1700, 내장그래픽 |
| CPU | Pentium Gold G7400 | 75,000~90,000원 | LGA1700, 내장그래픽 |
| CPU | i3-12100         | 140,000~160,000원 | → 70만원 미만 예산 초과 |
```
→ 50만원 빌드 CPU 예산 ~80,000원이면 LLM이 자동으로 G7400/G6900 선택.

---

### 7. Action 필드 비어있는 무한 루프
**증상**: 로그에 같은 스텝이 계속 반복됨:
```
[4] Success |  → CPU가 담겼으므로 목표 달성
[5] Success |  → CPU가 성공적으로 담겼으므로 목표 달성
⚠ 동일 액션 3회 반복
```

**원인**: LLM이 Predict 필드에 결론을 써버리고 `Action:` 줄을 출력하지 않음.
`parse_action("")` → `ValueError` → `action_error = True` 이지만
`eval_prev = "Success"` 상태라 실패 카운터가 증가하지 않음 → 동일 스텝 재실행 반복.

**해결**: `action_raw.strip() == ""` 를 명시적으로 체크 → observation에 강제 힌트 주입:
```python
if not action_raw.strip():
    observation = "Action: 필드가 비어있습니다. 목표 달성 시 반드시 DONE \"...\" 을 출력하세요."
```

---

### 8. mouse.wheel() 인자 오류
**증상**: `TypeError: Mouse.wheel() got multiple values for argument 'delta_x'`

**원인**: Playwright `mouse.wheel(delta_x, delta_y)`는 스크롤 양만 받음.
좌표 이동 없이 특정 위치에서 스크롤하려면 `mouse.move(x, y)` 를 먼저 호출해야 함.
```python
# 잘못된 코드:
await page.mouse.wheel(640, 500, delta_x=0, delta_y=600)
# 올바른 코드:
await page.mouse.move(640, 500)
await page.mouse.wheel(0, 600)
```

---

### 9. JS 스니펫 내 \n 이스케이프 오류
**증상**: `SyntaxError: Invalid or unexpected token` (Playwright page.evaluate)

**원인**: Python 삼중따옴표 문자열 안에서 `'\n'` 은 실제 줄바꿈 문자로 해석됨.
JS로 전달될 때 문자열 리터럴 중간에 줄바꿈이 삽입 → JS 파싱 에러.
```python
# Python: '\n' → JS: split('↵') → SyntaxError
text.split('\n')   # 잘못됨
text.split('\\n')  # 올바름 (JS: split('\n'))
```

---

### 10. sort_cheapest가 검색 결과 뷰에서 작동 안 함
**증상**: 메모리/SSD 검색 후 `TOOL sort_cheapest` 실행 → 검색 필터가 초기화되고 제품 목록이 사라짐.
다음 스크린샷에서 "제품 없음"으로 판단 → 에이전트가 재검색 루프.

**원인**: 다나와 PC견적의 sort 버튼(`onclick="estimateMainProduct.sort(...)"`)은 **카테고리 뷰 전용**.
`TOOL search "DDR4 8GB"` 실행 후에는 검색 결과 탭 뷰로 전환됨.
이 상태에서 sort 버튼 클릭 → 카테고리 뷰로 리셋 → 검색 필터 소멸.

**해결**: executor.py 시스템 프롬프트에 명시:
```
⚠️ TOOL search 이후에는 절대 sort_cheapest 사용 금지
→ 검색 후에는 바로 get_products → add_product
sort_cheapest는 TOOL select_category 이후 카테고리 뷰에서만 사용
```
**워크플로우 재설계**: 검색 대신 카테고리 + 필터 방식 우선 사용.

---

### 11. estimateMainProduct.sort() 직접 호출로 페이지 crash
**증상**: `sort_cheapest` 실행 후 `page.screenshot()` 30초 타임아웃.
`playwright._impl._errors.TargetClosedError: Page.wait_for_timeout: Target page... has been closed`

**원인**: `estimateMainProduct.sort('GOODSINFO_CASH_PRICE_ASC')` JS 함수를 `page.evaluate()`로 직접 호출 시
페이지 내부적으로 `window.location.reload()` 또는 form submit을 트리거하는 경우 발생.
Playwright 컨텍스트가 닫힘 → 이후 모든 playwright API 호출 실패.

**해결**: JS 함수 직접 호출 제거 → DOM 요소 클릭 방식으로 전환:
```javascript
// 제거한 코드: estimateMainProduct.sort('GOODSINFO_CASH_PRICE_ASC')
// 안전한 방법: onclick 속성 포함 요소 직접 클릭
const sortEl = Array.from(document.querySelectorAll('[onclick]'))
    .find(el => (el.getAttribute('onclick') || '').includes('CASH_PRICE_ASC'));
if (sortEl) sortEl.click();
```

---

### 12. add_product가 중고(中古) 제품 선택
**증상**: 메모리 검색 후 `TOOL add_product 2` → "삼성전자 DDR4-2133 **중고** (8GB) / 79,120원" 담김.
실제 신품 DDR4 8GB는 15,000~30,000원이므로 3배 이상 비쌈.

**원인**: `sort_cheapest` 실패 후 비정렬 상태에서 `get_products` 실행 → 목록에 중고 제품 혼재.
LLM이 제품명의 "중고" 표시를 놓치고 담기 실행.

**해결**: `_JS_ADD_PRODUCT`에 중고 필터 추가:
```javascript
const realBtns = allBtns.filter(btn => {
    const row = btn.closest('tr');
    if (!row || row.classList.contains('recom_area')) return false;
    const rowText = row.textContent || '';
    if (rowText.includes('중고') || rowText.includes('리퍼') || rowText.includes('재생')) return false;
    return true;
});
```
중고 제외 후 제품이 없으면 fallback으로 중고 포함 목록 사용.

---

### 13. add_product 성공 후 DONE 미출력 무한 루프
**증상**: `TOOL add_product 1 → 담기 완료` 후 에이전트가 DONE을 출력하지 못하고 빈 Action 반복:
```
[5] vision | Success |  → SSD 선택 완료
[6] vision | Success |  → SSD 선택 완료
⚠ 동일 액션 6회 반복 → 12스텝 초과
```

**원인**: `add_product` 성공 후 LLM이 DONE을 출력해야 하지만,
DONE 형식(`부품:카테고리 | 이름:제품명 | 가격:숫자`)에 넣을 정보를 찾지 못해 Action 필드를 비워둠.

**해결**: `last_add_product_obs` 변수로 마지막 `add_product` 관측값 추적.
빈 Action 반복 시 힌트에 제품 정보 포함:
```python
if not action_raw.strip() and last_add_product_obs:
    observation = (
        f"제품을 이미 담았습니다: {last_add_product_obs}. "
        f"반드시 DONE \"목표완료 | 부품:카테고리명 | 이름:제품명 | 가격:숫자\" 형식으로 출력하세요."
    )
```

---

### 15. get_products / add_product 제품명·가격 항상 실패 (루트 원인)
**증상**: `TOOL get_products` 실행 시 모든 제품이 `(제품명 없음)  |  인텔`처럼 표시됨.
`TOOL add_product 1` 성공 후에도 `담기 완료 | 이름:? | 가격:0` 반환.
→ `last_add_product_obs`에 정보가 없으니 DONE 루프가 계속 발생.

**원인**: `_JS_GET_PRODUCTS`와 `_JS_ADD_PRODUCT`에서 사용하는 DOM 셀렉터가 실제 다나와 PC견적 DOM과 전혀 일치하지 않았음.
브라우저에서 실제 DOM을 직접 확인한 결과:

```html
<!-- 실제 TR 구조 -->
<tr class="productList_12345678">
  <td class="goods_img">...</td>
  <td class="title_price">
    <p class="subject">
      <a class="">AMD 라이젠5-5세대 7400</a>   ← 빈 클래스 a 태그
    </p>
    <div class="spec_wrap">
      <span class="spec">AMD(소켓AM5)/6코어/12스레드/...</span>
    </div>
  </td>
  <td class="rig_line">
    <p class="low_price">207,240원</p>    ← 가격
    <a class="btn_choice2 wishAction">담기</a>
  </td>
</tr>
```

| 항목 | 기존 (틀린) 셀렉터 | 실제 DOM 셀렉터 |
|------|---------|---------|
| 제품명 | `a.goods_name`, `a[class*="name"]` | `td.title_price a[class=""]` |
| 스펙 | `.spec_list`, `.item_explain` | `td.title_price .spec` |
| 가격 | `.price_sect .num`, `.num` | `.prod_price` / `.low_price` |

**해결**: 브라우저에서 실제 DOM 확인 후 셀렉터 교체.
```javascript
// 제품명
const nameEl = tr.querySelector('td.title_price a[class=""]')
              || tr.querySelector('td.title_price .subject a');
// 스펙
const specEl = tr.querySelector('td.title_price .spec')
              || tr.querySelector('td.title_price .spec_wrap');
// 가격 (숫자만)
const priceEl = tr.querySelector('.prod_price') || tr.querySelector('.low_price');
```

**파급 효과**: 이 버그 하나가 여러 현상의 루트 원인이었음:
- `get_products` 제품명 없음 → LLM이 어떤 제품인지 모름
- `add_product` 이름/가격 `?`/`0` → `last_add_product_obs`에 의미 없는 정보
- DONE 힌트에 제품명/가격이 없으니 LLM이 DONE 형식 완성 불가 → 반복 루프

---

### 14. --no-step-budget 모드에서 비싼 CPU 선택
**증상**: `--no-step-budget` 실행 시 단계별 예산 없음 + 필수 검색어 "Pentium Gold G7400" 지정했는데
에이전트가 "더 좋은" i3-12100을 검색 → i3-12100F (벌크) 142,190원 선택.

**원인**: `--no-step-budget` 시 goal에 예산 제약이 없으므로 LLM이 "가장 좋은 것을" 선택하려 함.
"필수 검색어" 표현이 있어도 검색 후 자의로 다른 모델 검색 가능.

**해결 1**: `_build_goal` 수정 → `--no-step-budget` 시 힌트를 "참고 모델/규격"으로 변경.
에이전트가 카테고리+필터 방식을 우선하도록 유도.
**해결 2**: executor.py 규칙 추가:
```
"참고 모델/규격: X" → 방법 A(카테고리+필터) 우선 사용
→ filter "인텔(소켓1700)" + sort_cheapest + add_product 1
```

---

## 타 사이트 적용 전략 (쿠팡, 네이버 쇼핑 등)

weg-agent의 핵심 전략은 다나와 전용이 아니다. 구조를 분리했기 때문에 새 사이트 적용 시 교체가 필요한 부분이 명확하다.

### 계층별 이식성

| 계층 | 컴포넌트 | 이식성 | 설명 |
|------|----------|--------|------|
| **오케스트레이션** | `agent.py`, `planner.py`, `memory.py` | ✅ 그대로 사용 | 사이트 무관한 로직 |
| **인식** | `som.py` | ✅ 그대로 사용 | 순수 스크린샷, 사이트 무관 |
| **추론** | `executor.py` (AgentBrain 프롬프트 제외) | ✅ 거의 그대로 | TOOL 목록 설명만 교체 |
| **지식** | `knowledge.py` | 🔄 신규 작성 | 사이트별 UIRegion, 셀렉터 |
| **도구** | `tools.py` | 🔄 신규 작성 | 사이트별 DOM 조작 함수 |
| **탐색** | `ui_explorer.py` | 🔄 URL만 변경 | 새 URL로 자동 탐색 |

---

### 쿠팡 적용 시 필요한 작업

#### 1단계: UI 탐색으로 DOM 파악
```bash
# ui_explorer.py의 URL만 바꿔서 실행
DANAWA_ESTIMATE_URL = "https://www.coupang.com/np/search?..."
python ui_explorer.py
```
탐색기가 자동으로 카테고리 클릭, 스크롤, 필터 조작 → `knowledge/coupang_ui.json` 생성.

#### 2단계: tools.py 교체
쿠팡의 핵심 인터랙션을 DOM 기반 TOOL로 구현:

```python
# 예상 쿠팡 TOOL 목록
TOOL search "갤럭시 버즈"          # 검색창 입력 → 검색 버튼 클릭
TOOL filter "로켓배송"             # 배송 필터 체크박스
TOOL filter "쿠팡 판매"            # 판매자 필터
TOOL sort_cheapest                 # "낮은가격순" 셀렉트 변경
TOOL get_products                  # 상품 목록 (광고 자동 제외)
TOOL add_to_cart 1                 # n번째 상품 장바구니 추가
TOOL get_cart                      # 장바구니 현황
```

**쿠팡 DOM 특이사항 예측**:
- 검색 결과: `li[data-ad-info]` 또는 `data-vendor-item-id` → 광고 구분
- 장바구니 버튼: 아마도 `button[class*="cart"]` + AJAX 요청 → JS `.click()` 필요
- 로켓배송 필터: 체크박스가 `input[type="checkbox"]` + label 패턴 (다나와와 유사)
- 정렬: `select[name*="sort"]` 셀렉트 박스 또는 탭 버튼

#### 3단계: 플래너 프롬프트 교체
```python
# planner.py SYSTEM_PROMPT를 태스크에 맞게 교체
"쿠팡에서 최저가 상품을 장바구니에 추가하는 태스크..."
```

---

### 범용 적용 원칙 (어느 쇼핑몰이든)

#### 원칙 1: "클릭 가능한 모든 것은 DOM으로"
좌표 클릭은 viewport 크기, 스크롤 위치, 렌더링 타이밍에 모두 민감.
반면 DOM 클릭(`element.click()`)은 viewport 무관, 스크롤 위치 무관, jQuery/React 이벤트 모두 트리거.

```javascript
// 나쁜 방법: 좌표 추론
await page.mouse.click(934, 521)  // 픽셀 1개 차이로 실패

// 좋은 방법: DOM 직접
document.querySelector('.add-to-cart-btn').click()
```

#### 원칙 2: 광고/스폰서 제품 필터링
어느 쇼핑몰이든 검색 결과 상단에 광고 제품이 있음. DOM 클래스나 속성으로 구분:

| 사이트 | 광고 식별자 |
|--------|------------|
| 다나와 | `tr.recom_area` |
| 쿠팡 | `data-ad-info`, `[class*="sponsored"]` |
| 네이버 쇼핑 | `[class*="ad"]`, `data-nclick*="ad"` |
| G마켓 | `[class*="banner"]`, `li.ad_product` |

→ `get_products` TOOL에서 항상 광고 행을 필터링하고 1-indexed로 반환.

#### 원칙 3: 검색 방식 구분
```
전체 검색창 (상단 헤더)   → Enter / 검색 버튼 → 전체 사이트 검색 (페이지 이탈 위험)
카테고리 내 검색창        → 별도 버튼 클릭 → 현재 카테고리 내 필터링
필터 체크박스            → DOM 클릭 → 가장 안정적
```
**권장 우선순위**: 필터 체크박스 > 카테고리 내 검색 > 전체 검색

#### 원칙 4: JS 함수가 있으면 직접 호출
많은 쇼핑몰이 전역 JS 함수로 주요 동작을 처리:
```javascript
// 다나와: category(873, 2)
// 쿠팡: 예상 addToCart(itemId), selectOption(optionId)
// 일반 패턴 탐지:
typeof category === 'function'   // 다나와
typeof addToCart === 'function'  // 일부 쇼핑몰
```
→ `ui_explorer.py`가 탐색 중 `window` 전역 함수 목록을 수집하면 이를 자동 발견 가능.

#### 원칙 5: 상태 전이 지식 사전 구축 (Web-CogReasoner 방식)
에이전트가 매번 UI를 추론하는 대신 사전에 "클릭 → 결과" 매핑을 기록:

```json
{
  "trigger": "카테고리 버튼 'CPU' 클릭",
  "from_state": "카테고리 미선택",
  "to_state": "CPU 제품 1097개 목록 표시",
  "key_observation": "가운데 영역 제품 목록 변경, 오른쪽 패널 CPU 빨간 선택됨"
}
```
→ 에이전트가 현재 상태를 보고 "다음에 무엇이 필요한지" 지식 기반으로 빠르게 결정.

#### 원칙 6: 예산/가격 제약은 플래너에서 결정
executor가 실시간으로 가격을 보고 판단하는 것은 비효율적.
플래너가 컴포넌트별 예산을 **실제 시세 기반**으로 미리 할당:

```
❌ executor: "검색 → 가격 확인 → 비싸면 재검색" (불안정, 스텝 낭비)
✅ planner:  시세표 참고 → CPU 80,000원, RAM 25,000원 할당 → executor는 그냥 최저가 담기
```

---

## 파일별 역할

### `tools.py` — WALT 스타일 Danawa 전용 Tool

DOM을 직접 조작하는 고수준 액션. LLM이 좌표를 추론할 필요 없음.

```
TOOL select_category "CPU"       → JS: category(873, 2) 전역 함수 호출
TOOL filter "인텔(소켓1700)"      → JS: .item_checkbox 텍스트 매칭 → checkbox.click()
TOOL filter "DDR4"               → JS: 동일
TOOL clear_filters               → JS: 체크된 .item_checkbox input 전체 .click()
TOOL search "H610M"              → JS: #searchProduct 입력 → button.btn_search 클릭
                                      → 탭 분리 시 현재 카테고리 라디오 자동 선택
                                      ⚠ search 후 sort_cheapest 금지 — 검색 필터 리셋됨
TOOL sort_cheapest               → JS: onclick="...CASH_PRICE_ASC" 요소 클릭 (카테고리 뷰 전용)
                                      ⚠ estimateMainProduct.sort() 직접 호출 제거 — 페이지 crash 위험
TOOL get_products                → JS: tr[class*="productList_"]:not(.recom_area) 수집 (광고 자동 제외)
                                      제품명: td.title_price a[class=""], 가격: .prod_price (v6 수정)
TOOL add_product N               → JS: .btn_choice2.wishAction (광고+중고+리퍼 제외) N번째 .click()
                                      중고 제외 후 제품 없으면 fallback 없이 오류 반환 (v6 수정)
TOOL remove_part "메인보드"       → JS: dd.select 카테고리명 매칭 → 삭제 버튼 .click()
TOOL get_cart                    → JS: 오른쪽 패널 선택 부품 목록 텍스트 반환
```

**핵심 워크플로우 (v5 기준)**:
```
✅ 방법 A: 카테고리 + 필터 방식 (sort 가능 — 모든 부품 권장)
TOOL select_category "메모리" → TOOL filter "DDR4" → TOOL sort_cheapest → TOOL get_products → TOOL add_product 1
TOOL select_category "CPU" → TOOL filter "인텔(소켓1700)" → TOOL sort_cheapest → TOOL get_products → TOOL add_product 1

✅ 방법 B: 검색 방식 (sort 금지 — 특정 모델명 알 때)
TOOL select_category "메인보드" → TOOL search "H610M" → TOOL get_products → TOOL add_product 1

✅ 방법 C: SSD 전용 (반드시 카테고리+필터 — 검색 방식 사용 금지)
TOOL select_category "SSD" → TOOL filter "256GB" → TOOL filter "M.2 (NVMe)" → TOOL sort_cheapest → TOOL get_products → TOOL add_product 1

❌ 금지: TOOL search 후 TOOL sort_cheapest → 검색 필터 리셋
❌ SSD에서 TOOL search "256GB NVMe SSD" 사용 금지 → 필터 방식만 사용
```

### `knowledge.py` — Factual Knowledge Base (Web-CogReasoner 영감)

```python
DanawaKnowledge:
    url: str                          # 실제 PC견적 URL
    regions: list[UIRegion]           # 페이지 영역별 요소 정보
    state_transitions: list[...]      # 클릭 → 상태변화 기록
    scroll_areas: list[ScrollArea]    # 스크롤 가능 영역
    workflow: list[str]               # 권장 작업 순서
    quirks: list[str]                 # 사이트 특이사항

BASE_KNOWLEDGE:
    - 카테고리 버튼: dd[class*="category_"].pd_item > a.pd_item_title
    - 카테고리 ID: CPU=873, 메인보드=875, 메모리=874, SSD=32617, 케이스=879, 파워=880
    - 검색창: #searchProduct (btn_search 클릭으로 실행)
    - 담기 버튼: .btn_choice2.wishAction (jQuery → JS .click() 필수)
    - 광고: tr.recom_area (자동 필터링)
```

### `ui_explorer.py` — 능동적 UI 탐색기

```
Phase 1: 초기 상태 스크린샷 + DOM 샘플 → LLM 분석
Phase 2: 카테고리 버튼 순서대로 클릭 → before/after 스크린샷 비교 → 상태 전이 기록
Phase 3: 스크롤 탐색 (메인 영역 + 오른쪽 패널) → 숨겨진 콘텐츠 발견
Phase 4: 검색 실험 → 결과 구조 분석
```

결과를 `knowledge/danawa_ui.json`에 저장. 다음 실행 시 재사용.

### `executor.py` — 미니 ReAct + AgentBrain

```
Eval:    Success
Memory:  Pentium Gold G7400 검색 완료, 85,000원
Predict: sort 후 최저가 G7400이 1번에 표시될 것
Goal:    낮은가격순 정렬 후 담기
Action:  TOOL sort_cheapest
```

**Predict 필드 효과**: 액션 전 예상 결과를 명시 → 이상한 예측이면 LLM이 스스로 수정.

### `planner.py` — 계획 수립 + 시세표

실제 다나와 시세를 프롬프트에 포함 → LLM이 예산에 맞는 모델을 처음부터 정확히 추천.

```
50만원 CPU 예산 ~80,000원 → hint: "Pentium Gold G7400"  ✅
                          → hint: "i3-12100" (150,000원) ❌ (시세표 없으면 이렇게 나옴)

SSD hint 전략 (v5):
→ hint: "256GB NVMe" (카테고리+필터 방식: filter "256GB" + filter "M.2 (NVMe)")
→ executor가 hint를 보고 방법 C(SSD 전용 필터 워크플로우) 실행
→ hint: "256GB NVMe SSD" 검색어로 사용 금지 — 다나와 SSD 검색이 불안정
```

---

## 기술 출처

| 기술 | 출처 | 적용 |
|------|------|------|
| **Planner-Executor 분리** | Go-Browse (ApGa, 2025) | `planner.py` + `executor.py` |
| **Replanner (실패 복구)** | Go-Browse | `agent.py` replan() |
| **WALT Tool 추상화** | WALT (Salesforce AI, 2024) | `tools.py` 전체 |
| **Hybrid deterministic+agentic** | WALT | TOOL + CLICK 혼용 |
| **광고 자동 스킵** | WALT (Tool이 노이즈 처리) | `add_product` recom_area 필터 |
| **AgentBrain 4-field** | Browser Use | `Eval/Memory/Goal/Action` |
| **Predict 필드** | weg-agent 자체 확장 | 액션 전 예측으로 hallucination↓ |
| **순수 Vision** | OpenAI CUA / Claude Computer Use 트렌드 | `som.py` 단순화 |
| **Factual/Procedural 지식 분리** | Web-CogReasoner (ICLR 2026) | `knowledge.py` 구조 |
| **능동적 UI 탐색** | Go-Browse inner loop | `ui_explorer.py` Phase 1~4 |

---

## 설치 및 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# .env에 LETSUR_API_KEY 입력

# 기본 실행 (50만원 사무용)
python main.py --task office_50 --no-eval

# 단계별 예산 제한 없이 실행 (최저가 자동 선택)
python main.py --task office_50 --no-step-budget --no-eval

# UI 탐색 먼저 실행 (첫 실행 또는 사이트 변경 시)
python ui_explorer.py

# headless 모드
python main.py --headless
```

---

## 테스트 케이스

| ID | 예산 | 목적 | 필수 부품 |
|----|------|------|----------|
| `office_50` | 50만원 | 사무용 | CPU(내장그래픽) + 메인보드 + RAM 8GB↑ + SSD 256GB↑ + 케이스 + 파워 |
| `gaming_100` | 100만원 | 게이밍 | 위 + GPU (RTX 4060 급) |
| `budget_30` | 30만원 | 최저가 | CPU(내장그래픽) + RAM 8GB + SSD 128GB↑ |

---

## 개선 방향

### 단기
- **get_cart DOM 셀렉터 검증**: `.pc_result`, `.estimate_result` 등 실제 다나와 DOM과 불일치 가능성
- **remove_part 검증**: 부품 담은 후 X 버튼 실제 클래스명 확인 필요
- **Replanner 횟수 제한**: 현재 무한 replan 가능 → 최대 2회로 제한

### 중기
- **타 사이트 tools.py 자동 생성**: `ui_explorer.py`가 DOM 탐색 결과를 바탕으로 tools.py 코드 자동 생성
- **trajectory 수집 → few-shot**: `results/*.json` 성공 사례를 다음 실행 few-shot으로 주입
- **Go-Browse 상태 그래프**: Danawa UI를 DAG로 모델링 → 현재 어느 페이지인지 추적

### 장기
- **다중 사이트 가격 비교**: 다나와 + 쿠팡 + 네이버 쇼핑 동시 비교 후 최저가 선택
- **Web-CogReasoner 파인튜닝**: 성공 trajectory로 소형 모델(7B) 학습 → API 비용 절감

---

## Web Transition Memory Research

이 저장소에는 web transition memory 연구용 메모와 baseline 스크립트도 함께 둔다.

- 허브: [research_note/web_transition/README.md](research_note/web_transition/README.md)
- 노트: `research_note/web_transition/notes/`
- 실행 스크립트: `research_note/web_transition/baselines/`
- 결과 저장 규칙: `eval_results/<provider>/<model>/<run_id>/<baseline>/task<example>_0/`

핵심 비교 축은 `Synapse / AWM / ReasoningBank / WMA / RAP / Ours`이고,
모두 `memory_view / expected_transition / failure_signal / verification_rule` 슬롯으로 맞춘다.
