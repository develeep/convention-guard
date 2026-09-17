# 규칙 파일 형식 1.0

## 목차
- 전체 필드
- detect: 앵커와 조건
- tests: 픽스처의 의미
- semantic_review: 의미 판정
- fix.auto: 자동 수정
- override: 부분 덮어쓰기
- 검증 오류 메시지

## 전체 필드

```yaml
id: no-direct-slack-call          # 파일명과 같게. core/ local/ user/ 는 자동으로 붙음
title: Slack 은 NotificationService 경유
severity: warn                    # error(차단) | warn(error 에 편승) | info(기록만)
applies_to:
  stacks: [php]                   # 필수. 감지된 스택 태그 중 하나라도 맞으면 적용. ["*"] = 전부
  files: ["app/**/*.php"]         # 생략 = 모든 파일
  exclude: ["app/Services/NotificationService.php"]
  version: ">=10"                 # 선택. {laravel: ">=10"} 형태도 가능
superseded_by: [pint.json]        # 이 파일이 레포에 있으면 규칙이 물러남 (포맷 규칙용)
detect: {...}                     # 아래
semantic_review: {...}            # 선택. 아래
message: |                        # 위반일 때 에이전트가 읽는 지침: 문제 한 줄 + 할 일 한 줄
  ...
prevent: 쓰기 전에 알아야 할 한 줄   # 선택. setup.py emit 이 컨텍스트로 내보냄
fix: {...}                        # 선택. 아래
tests:
  match: [...]                    # 걸려야 하는 것 (1개 이상 필수)
  no_match: [...]                 # 걸리면 안 되는 헷갈리는 정상 코드
```

글롭: `**/` 는 디렉터리를 넘나들고, `*` 는 한 디렉터리 안, `{a,b}` 는 선택.

## detect: 앵커와 조건

앵커는 정확히 하나입니다.

| 앵커 | 조건 | 걸리는 때 |
|---|---|---|
| `when_line_added: '<정규식>'` | — | 추가된 줄이 패턴에 맞음 |
| `when_line_added: '<정규식>'` | `must_contain_in_file: '<정규식>'` | 추가된 줄이 맞고, 파일 전체에 필수 요소가 없음 (파일당 1건) |
| `when_file_added: true` | `must_contain_in_file: '<정규식>'` | 새 파일에 필수 요소가 없음 |
| `when_changed: [글롭]` | `require_changed: [글롭]` | 변경 집합에 A 는 있고 B 는 없음 |
| `file_regex: '<정규식>'` | — | 파일 전체에서 매치된 구간이 변경된 줄과 겹침 |

`flags: i` 로 대소문자 무시. 정규식은 Python `re` 문법이고, YAML 에서는 작은따옴표로 감쌉니다 (안의 `'` 는 `''`).

## tests: 픽스처의 의미

| 앵커 | 픽스처 하나 = |
|---|---|
| `when_line_added` | 코드 한 줄 |
| `+ must_contain_in_file` | 파일 본문 (조건 줄은 있고 필수 요소는 없으면 match) |
| `when_file_added` | 새 파일 본문 (필수 요소가 없으면 match) |
| `when_changed` | 변경된 경로 목록 `["routes/api.php", "app/X.php"]` |
| `file_regex` | 여러 줄 코드 |
| semantic_review 규칙 | 게이트만 검사 (판정은 리뷰어 몫) |

## semantic_review: 의미 판정

`detect` 가 게이트가 되고, 후보는 에이전트에게 바로 가지 않고 `convention-reviewer` 에게 갑니다. 게이트를 좁게 잡을수록 판정 요청이 줄어듭니다.

```yaml
semantic_review:
  context:
    - current_function                  # 후보를 감싸는 함수 (기본값)
    - imports                           # 파일 상단 import/use
    - changed_hunks                     # 같은 파일에서 이번 변경이 추가한 다른 줄
    - snippet                           # 후보 ±5줄
    - related_files:                    # 함수 안의 심볼로 찾은 파일의 앞부분
        symbol: '\b([A-Z]\w+)::query\b' #   첫 번째 캡처 그룹이 심볼
        glob: 'app/Models/{1}.php'      #   {1} 에 심볼이 들어감
        max: 2
  max_context_lines: 150
  instruction: |
    무엇을 보고 VIOLATION / VALID 를 가를지.
    VIOLATION: <구체 조건>
    VALID: <구체 조건>
    판단할 수 없으면 VALID 입니다.
```

instruction 에는 반드시 "판단할 수 없으면 VALID" 를 넣습니다. 레포 전체를 탐색하라는 지시는 넣지 않습니다 — 컨텍스트 팩으로 판정할 수 있는 규칙만 의미 판정으로 만듭니다.

## fix.auto: 자동 수정

`when_line_added` 단독 규칙만. `mode: auto-fix` 또는 `scan.py --fix` 에서 후보 줄에만 적용됩니다.

```yaml
fix:
  auto:
    replace: '\(\s*(int|string)\s*\)'   # Python re.sub 패턴
    with: '(\1)'
```

픽스처 검사가 확인하는 것: 모든 `match` 가 수정 후 더 이상 걸리지 않음, 모든 `no_match` 는 바뀌지 않음.

## override: 부분 덮어쓰기

```yaml
override: core/laravel-no-query-in-blade
severity: warn
applies_to:
  exclude: ["resources/views/admin/**"]
```

원본에 깊은 병합됩니다. 목록은 합쳐지지 않고 **교체**됩니다 (위 예시에서 exclude 는 admin 경로 하나가 됨).

## 검증 오류 메시지

| 메시지 | 고칠 것 |
|---|---|
| 0.x 규칙 형식입니다 | `triggers`/`context_injection` 등 → `scripts/migrate.py` |
| applies_to.stacks 가 필요합니다 | 스택 태그 또는 `["*"]` |
| 앵커가 정확히 하나 있어야 합니다 | detect 의 앵커 키 정리 |
| when_file_added 에는 must_contain_in_file 이 필요합니다 | 조건 추가 |
| 어느 프리셋에도 속하지 않아 실행되지 않습니다 | (플러그인 규칙) `presets/*.yaml` 의 rules 에 id 추가 |
| fix.auto 가 위반을 고치지 못함 | replace/with 수정 |
