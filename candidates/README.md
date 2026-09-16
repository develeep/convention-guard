# candidates/ — 아직 규칙이 아닌 규칙 후보

여기 있는 파일은 **규칙이 아닙니다.** 훅은 이 디렉터리를 읽지 않습니다.
`scripts/survey.py` 가 레포 전체를 훑어 "이 레포가 이미 이렇게 쓰고 있는가"를 센 다음,
숫자와 함께 후보로 제시하는 목록입니다. 채택하면 그때 레포의
`.claude/convention-rules/` 로 복사되어 규칙이 됩니다.

규칙을 추천한다는 건 결국 **팀이 이미 지키고 있는 것을 굳히는 일**입니다.
92%가 한 방향으로 쓰고 있다면 그건 컨벤션이고, 남은 8%는 회귀입니다.
50:50이면 컨벤션이 아니라 취향 차이이고, 그걸 규칙으로 만들면 오탐으로만 보입니다.
그래서 후보는 **찬성 근거(정상 패턴)와 반대 근거(위반 패턴)를 둘 다** 들고 있어야 합니다.

## 형식

규칙 파일 형식(`rules/**`)에 세 키를 더한 것입니다. 채택할 때 그 세 키는 떨어져 나갑니다.

```yaml
id: laravel-controller-no-eloquent      # local/ 네임스페이스는 채택 시 자동
title: 컨트롤러에서 Eloquent 직접 호출 금지
severity: warn                          # 채택 기본값. --severity 로 덮어쓸 수 있음
applies_to:
  stack: [laravel]
  files: ["app/Http/Controllers/**/*.php"]
  exclude: ["**/vendor/**"]
triggers:
  code_regex: '\b[A-Z]\w+::(where|find|create|update)\s*\('
context_injection: |
  컨트롤러에서 모델을 직접 조회하고 있습니다. 서비스나 리포지터리를 거치세요.

# --- 카탈로그 전용 키 (채택 시 제거됩니다) ---
probe:
  conforming: '\$this->\w*(service|repository|repo)\w*->'
rationale: 조회 로직이 컨트롤러에 퍼지면 재사용과 테스트가 모두 어려워집니다.
covered_by: core/laravel-controller-needs-validation   # 선택: 이미 공통 규칙이 덮는 경우

tests:
  should_match:
    - '        $orders = Order::where("user_id", $id)->get();'
  should_not_match:
    - '        $orders = $this->orderService->forUser($id);'
```

| 키 | 뜻 |
|---|---|
| `probe.conforming` | **정상 패턴.** 이 정규식이 걸리는 파일은 컨벤션을 지키는 파일로 셉니다 |
| `rationale` | 왜 이 컨벤션이 값어치가 있는지 한 줄. 추천 목록에 그대로 출력됩니다 |
| `covered_by` | 이미 같은 일을 하는 공통 규칙 id. 그 규칙이 켜져 있으면 추천에서 중복으로 표시됩니다 |

`probe.conforming` 이 없으면 준수율을 셀 수 없으므로 후보로 인정되지 않습니다.
`tests` 픽스처도 필수입니다 — `python3 tests/run_all.py` 가 카탈로그까지 검증합니다.
추천이 오탐 정규식을 들고 오는 것은, 규칙이 오탐인 것보다 나쁩니다.

## 판정 기준

`survey.py` 가 레포 전체를 훑어 파일 단위로 셉니다.

| 판정 | 조건 | 뜻 |
|---|---|---|
| 이미 100% 준수 | 위반 0, 준수 ≥3 | 회귀 방지용. `error` 로 켜도 안전합니다 |
| 추천 | 준수율 ≥80% | 컨벤션이 있습니다. `warn` 으로 시작하세요 |
| 합의 필요 | 준수율 30~80% | 팀이 갈려 있습니다. 규칙보다 논의가 먼저입니다 |
| 표본 부족 | 해당 파일 3개 미만 | 한 건씩으로는 컨벤션인지 알 수 없습니다 |
| 반대 관습 | 준수율 <30% | 이 레포는 반대로 씁니다. 추천하지 않습니다 |
| 해당 코드 없음 | 준수 0, 위반 0 | 아직 그런 코드가 없습니다 |

## 레포 전용 후보

에이전트가 이 레포에서 발견한 컨벤션은 `<repo>/.claude/convention-rules/candidates/`
에 같은 형식으로 두면 됩니다. 측정은 카탈로그 후보와 똑같이 엔진으로 돌아가므로,
"에이전트가 그렇게 보였다"가 아니라 숫자로 검증된 뒤에만 목록에 오릅니다.
