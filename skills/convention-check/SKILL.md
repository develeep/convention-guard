---
name: convention-check
description: 훅을 기다리지 않고 지금 convention-guard 검사를 실행해 결과를 판정·정리하고, 요청받으면 고친 뒤 다시 검사합니다. 워킹 트리·스테이지·브랜치 범위·지정 파일·레포 전수조사를 지원하고, 오탐은 기각 기록으로 남기며, 의미 판정 규칙은 convention-reviewer 에이전트에 맡깁니다. "컨벤션 검사해줘", "규칙 위반 있는지 봐줘", "PR 올리기 전에 확인", "이 브랜치 검사", 커밋 직전 점검, CI 에 검사를 넣을 때 사용합니다.
---

# 컨벤션 검사 실행

Stop 훅과 **같은 파이프라인**을 씁니다. 수동 결과와 훅 결과가 다르면 둘 다 믿을 수 없게 되기 때문입니다.

## 체크리스트

```
- [ ] 1. 범위 고르기
- [ ] 2. scan.py 실행
- [ ] 3. 결정론 후보 판정 (직접 Read)
- [ ] 4. semantic 후보가 있으면 --review → convention-reviewer 에게 위임
- [ ] 5. 오탐은 기각 기록, VIOLATION 만 위반으로 보고
- [ ] 6. (요청 시) 고치고 재검사
```

후보는 두 종류이고, **판정하는 주체가 다릅니다**.

```
scan.py
  ├ 결정론 후보 (detect 만 있는 규칙)
  │    → 메인 에이전트가 필요한 최소 코드 맥락을 Read 해서 판정
  │
  └ semantic 후보 (semantic_review 가 있는 규칙)
       → scan.py --review → 판정 배치 → convention-reviewer 에이전트
       → VIOLATION / VALID / FALSE_POSITIVE 기록 → VIOLATION 만 돌아옴
```

의미 판정을 별도 에이전트에게 맡기는 이유: 판정에는 함수 본문·관련 모델 같은 코드 맥락이 필요한데, 그것을 메인 대화에 쌓지 않기 위해서입니다. 서브에이전트가 컨텍스트 팩을 읽고 판정 근거를 기록하며, 메인 대화에는 명령 한 줄과 위반 목록만 오갑니다. 판정은 캐시에 남아 같은 코드를 두 번 판정하지 않습니다.

### 1. 범위 고르기

사용자의 말에서 고릅니다. 애매하면 워킹 트리로 시작하고, 결과를 보여준 뒤 넓힐지 묻습니다.

| 요청 | 옵션 |
|---|---|
| (기본) 지금 바뀐 것 | 없음 |
| 커밋 직전 | `--staged` |
| PR 올리기 전, 브랜치 전체 | `--range origin/main..HEAD` |
| 이 파일 | `--files app/X.php` |
| 레거시 규모, 도입 전 감사 | `--all`  |

`--all`은 기존 레거시 코드까지 대량으로 검사할 수 있으므로 사용자가 명시적으로 요청한 경우에만 사용합니다.

기각 기록을 무시하고 전부 보려면 `--no-dismiss` 를 붙입니다 (규칙 점검용).

### 2. scan.py 실행

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan.py" --no-color
```

scan.py는 결정론적인 검사를 수행하고, 컨벤션 위반 가능성이 있는 후보(candidate) 를 출력합니다.

종료 코드:

0: 검사 결과 위반 없음
1: 위반 발견
2: 검사 불가

`2` 결과가 없는게 아니라 Git 저장소가 아니거나, 범위가 잘못되었거나, 설정 오류 등으로 검사를 완료하지 못한 경우이므로 stderr를 확인하고 사용자에게 검사 실패 원인을 전달합니다. 

옵션 전체와 CI 연동: [references/cli.md](references/cli.md)

### 3. 결정론 후보 판정

출력은 정규식이 좁힌 **후보**입니다. 그대로 붙여넣지 말고, 각 위치를 `Read` 로 열어 규칙의 지침(`→` 줄)에 비춰 위반인지 판단합니다. 판단에 필요한 최소한만 읽습니다.

- 린터 실패는 확정 위반입니다. 판정 없이 맨 앞에 둡니다.
- 요약의 `semantic 규칙 후보 N건` 은 **여기서 판정하지 않습니다** — 4단계로 갑니다. 그 후보의 코드를 직접 Read 해서 판정하지 마세요.

### 4. semantic 후보는 convention-reviewer 에게

2단계 요약에 `semantic 규칙 후보 N건` 이 **0건이면 이 단계를 건너뜁니다** — 리뷰어를 부르지 않습니다.

1건 이상이면 같은 범위에 `--review` 를 붙여 다시 실행합니다. 판정 배치가 만들어지고, 출력 끝에 리뷰어에게 넘길 명령 한 줄이 나옵니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan.py" --review --no-color
```

그 `review.py show "<배치 경로>"` 한 줄을 `convention-guard:convention-reviewer` 에이전트에게 그대로 넘기고, 돌아온 VIOLATION 목록만 결과에 넣습니다. 절차와 캐시 동작: [references/semantic.md](references/semantic.md)

### 5. 오탐은 기각 기록, 위반은 보고

오탐을 말로만 넘기면 로그에서 "안 고침"과 구분되지 않아, 나중에 rule-tune 이 건강한 규칙을 오탐으로 읽습니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dismiss.py" --rule <규칙id> --file <파일> --line <줄> --reason "<코드에 근거한 한 줄>" --by agent
```

기각 기준과 파일 전체 기각: [references/dismiss.md](references/dismiss.md)

보고에 넣는 것은 **확정된 위반**뿐입니다: 린터 실패, 3단계에서 위반으로 판정한 결정론 후보, 리뷰어가 `VIOLATION` 으로 돌려준 semantic 후보. 리뷰어의 `VALID`·`FALSE_POSITIVE` 는 위반이 아니므로 보고하지 않습니다 (판정은 이미 기록됐고, rule-tune 이 그 차이로 규칙을 손봅니다).

보고는 규칙별로 묶고, 위반마다 위치와 고칠 방법 한 줄. 20건이 넘으면 규칙별 건수로 요약하고 상위 몇 개만 보여줍니다. 지적 0건이면 그대로 보고하고 끝냅니다 — 범위를 넓혀 억지로 찾지 않습니다.

### 6. 고치고 재검사

사용자가 고치라고 했을 때만 고칩니다. error 부터, 규칙 하나씩, 고칠 때마다 같은 범위로 다시 실행합니다.
`--fix` 로 자동 수정안이 있는 규칙은 먼저 적용할 수 있습니다:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan.py" --fix --no-color            # 수정안 미리보기
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan.py" --fix --write --no-color    # 적용 후 남은 것 보고
```

semantic 위반을 고쳤으면 재검사도 `--review` 로 합니다. 함수 본문이나 규칙이 바뀐 후보만 다시 판정 대상이 됩니다.

재검사에서 **새로 생긴** 지적이 있으면 방금 수정이 만든 것입니다. 그 수정부터 다시 봅니다.

적용되는 규칙이 0개로 나오면 스택 감지 문제입니다: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/detect_stack.py"`
