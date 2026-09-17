# 기각 기록

`<repo>/.claude/convention-guard/dismissed.yaml` 에 남고, 커밋해서 팀과 공유하는 파일입니다.

## 언제 기각하는가

| 상황 | 할 일 |
|---|---|
| 규칙이 막으려는 문제가 이 코드에는 없다 (예: 공개가 목적인 키) | 기각 |
| 규칙에는 맞지만 고치는 편이 더 나쁘다 (예: 끊으면 읽기 어려운 체이닝) | 기각 + 이유에 트레이드오프 |
| 위반이지만 지금 고칠 시간이 없다 | **기각하지 않음** — 보고만 |
| 같은 이유로 여러 곳이 걸린다 | 기각을 반복하지 말고 rule-tune 으로 규칙을 좁히자고 제안 |

이유는 코드에 근거한 한 줄입니다. "오탐" 같은 한 단어는 rule-tune 이 규칙을 좁힐 재료가 되지 못합니다.

## 명령

```bash
S="${CLAUDE_PLUGIN_ROOT}/scripts"

# 한 위치 — 그 코드의 지문이 기록되고, 코드가 바뀌면 다시 지적됨
python3 "$S/dismiss.py" --rule core/php-line-too-long --file app/X.php --line 84 \
  --reason "체이닝을 끊으면 쿼리 흐름이 안 보임" --by agent

# 훅이 알려준 키 그대로 (다시 검사하지 않음)
python3 "$S/dismiss.py" --key core/php-line-too-long:app/X.php:6f1c93ab24 --reason "..." --by agent

# 파일 전체에서 규칙 끄기 — 만료되지 않으므로 드물게
python3 "$S/dismiss.py" --rule core/js-no-console --file scripts/seed.ts --whole-file \
  --reason "시드 스크립트는 콘솔 출력이 인터페이스" --by agent

python3 "$S/dismiss.py" --list
```

사람이 판단한 것은 `--by human`(기본값), 에이전트가 판단한 것은 `--by agent` 입니다.

## 거부되는 경우

| 메시지 | 뜻 |
|---|---|
| 지금 그 위치에서는 이 규칙이 걸리지 않습니다 (종료 1) | 코드가 이미 바뀌었거나 줄 번호가 틀림. 다른 위치를 대신 기각하지 않습니다 |
| 이 파일에 N곳이 걸립니다 (종료 2) | `--line` 으로 하나를 고르거나 `--whole-file` |
| 파싱 실패 (종료 2) | dismissed.yaml 이 깨졌습니다. 이 상태에서는 훅도 검사를 건너뜁니다. 파일을 고친 뒤 다시 실행 |
| 이미 기록돼 있습니다 (종료 0) | 중복 기록하지 않았습니다 |
