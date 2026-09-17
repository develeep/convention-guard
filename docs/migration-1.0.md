# 0.x → 1.0 마이그레이션

1.0 은 레포 설정 위치, 설정 키, 규칙 형식이 바뀝니다. 0.x 설정이 남아 있으면 훅은 검사를 건너뛰고 `migrate.py` 를 안내합니다 — 팀이 고르지 않은 기본값으로 차단하지 않기 위해서입니다.

## 한 번에 옮기기

```bash
python3 scripts/migrate.py                 # 무엇이 바뀌는지 diff 로 미리보기
python3 scripts/migrate.py --write         # 적용 (옛 파일 삭제)
python3 scripts/migrate.py --user --write  # ~/.claude/convention-rules 의 개인 규칙
python3 scripts/detect_stack.py            # 노트에 error 가 없는지 확인
```

- 주석은 보존됩니다. 줄 단위로 변환하기 때문입니다
- 규칙마다 변환 전후의 의미(패턴, 대상 파일, 강도, 메시지, 픽스처)가 같은지 검증하고, 다르면 그 파일은 쓰지 않고 `✗` 로 보고합니다
- 종료 코드: 0 옮길 것 없음·완료, 1 미리보기에서 변경 있음, 2 검증 실패

## 무엇이 바뀌나

### 위치

| 0.x | 1.0 |
|---|---|
| `.claude/convention-rules/config.yaml` | `.claude/convention-guard/config.yaml` |
| `.claude/convention-rules/dismissed.yaml` | `.claude/convention-guard/dismissed.yaml` |
| `.claude/convention-rules/**/*.yaml` (규칙) | `.claude/convention-guard/rules/**` |
| `~/.claude/convention-rules/` | `~/.claude/convention-guard/rules/` |

### 설정 키

| 0.x | 1.0 |
|---|---|
| `block_level: error` / `report` | `mode: fix` / `report` |
| `max_rules` | `limits.max_error_rules` |
| `max_warns` | `limits.max_warn_rules` |
| `max_hits_per_rule` | `limits.max_locations_per_rule` |
| `max_consecutive_blocks` | `limits.max_consecutive_blocks` |
| `run_linters`, `lint_timeout` | `linters.enabled`, `linters.timeout` |
| `base_ref` | `scope.base_ref` |
| `semantic_review: true` | `semantic_review.enabled: true` |
| `max_semantic_rules` | `semantic_review.max_candidates` |
| `max_semantic_reviews_per_session` | 삭제 — 후보 지문으로 중복 판정을 막음 |
| (없음) | `presets`, `limits.max_verify_attempts`, `mode: auto-fix` |

### 규칙 형식

| 0.x | 1.0 |
|---|---|
| `applies_to.stack` | `applies_to.stacks` (필수 — 없던 규칙에는 `["*"]` 가 들어감) |
| `triggers:` | `detect:` |
| `code_regex` | `when_line_added` |
| `absent_in_new_file: X` | `when_file_added: true` + `must_contain_in_file: X` |
| `review_when` + `review_prompt` | `when_line_added` + `semantic_review.instruction` |
| `context_injection` | `message` |
| `context_line` (+ `in_context`) | `prevent` |
| `tests.should_match` / `should_not_match` | `tests.match` / `no_match` |

규칙 id 와 기각 지문 알고리즘은 그대로라서 `dismissed.yaml` 과 config 의 `disable`/`severity` 는 수정 없이 동작합니다.

### 동작

| 영역 | 0.x | 1.0 |
|---|---|---|
| 차단 후 | 요청당 1회 차단, 다음 Stop 은 측정만 | 같은 범위 재검증, 남거나 새로 생긴 error 는 한 번 더 차단 |
| 의미 판정 | `type: agent` 훅을 수동으로 교체해 매 Stop 실행 | 후보가 있고 판정 기록이 없을 때만 `convention-reviewer` 에이전트에 위임 |
| core 규칙 로드 | 스택 태그로만 거름 | 활성 프리셋에 속한 규칙만 (`presets: auto` 는 0.x 와 거의 같음, `architecture`/`performance` 는 명시) |
| `layer-boundary` | 기본 로드 | `architecture` 프리셋을 켜야 함 |
| 발동 로그 | `match`/`followup` 이벤트 | schema 2 (`candidate`/`block`/`verify`/`verdict` …) — `log_report.py` 는 0.x 행을 건너뜀 |
| 훅 파일 | `hooks.with-semantic-review.json` 교체 | 삭제. `hooks.json` 하나 |
| 스크립트 | `check.py --explain`, `emit_rules.py`, `test_rules.py` | `detect_stack.py`, `setup.py emit`, `tests/rules/test_rule_fixtures.py` |

## 생성된 문서

`emit_rules.py` 가 만든 `.claude/rules/convention-*.md` 나 CLAUDE.md 관리 블록은 `setup.py emit` 으로 다시 만드세요. 관리 블록 밖의 내용은 보존됩니다.

```bash
python3 scripts/setup.py emit --stdout
python3 scripts/setup.py emit            # 또는 --agents-md / --claude-md
```
