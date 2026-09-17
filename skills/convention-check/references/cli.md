# scan.py 옵션과 CI

## 범위 (하나만)

| 옵션 | 검사 대상 | 앵커 |
|---|---|---|
| (없음) | 워킹 트리: HEAD 대비 변경 + 새 파일 | 추가된 줄만 |
| `--staged` | 스테이지된 변경 | 추가된 줄만 |
| `--range A..B` | 리비전 범위 | 추가된 줄만 |
| `--files a b` | 지정 파일 전체 | 파일 전체를 새 파일로 취급 |
| `--all` | 추적 중인 모든 텍스트 파일 | 파일 전체를 새 파일로 취급 |

`--base-ref <ref>` (워킹 트리 전용): HEAD 대비 변경에 `<ref>` 대비 변경을 합칩니다. 세션 중에 커밋해 버린 변경까지 보려면 `--base-ref auto` (기본 브랜치와의 merge-base).

## 출력·필터

| 옵션 | 효과 |
|---|---|
| `--severity error` | 이 강도 이상만 **출력**. 종료 코드는 모든 지적으로 판단 |
| `--rule <일부 문자열>` | id 에 이 문자열이 들어간 규칙만 |
| `--no-lint` | 린터 위임 생략 (빠름) |
| `--no-dismiss` | 기각 기록을 무시하고 전부 — 무엇이 억제돼 있는지 볼 때 |
| `--max-hits N` | 규칙당 위치 수 (기본 10) |
| `--json` | 기계가 읽을 형태. `head.review`, `head.fixes` 포함 |
| `--fix` / `--fix --write` | 자동 수정안 보기 / 적용 |
| `--review` | 의미 판정 배치 생성 + 캐시된 VIOLATION 판정을 결과에 포함 |

## 종료 코드

| 코드 | 뜻 |
|---|---|
| 0 | 통과 (`--fail-on` 기준 미만) |
| 1 | `--fail-on` 이상의 지적, 또는 변경 줄에 걸린 린터 실패 |
| 2 | 검사 불가 — git 아님, 범위 해석 실패, 레포 밖 경로, 규칙·설정·기각 파일 오류 |

`--fail-on`: `error`(기본) / `warn` / `info` / `never`.

## CI

```yaml
- run: |
    python3 plugins/convention-guard/scripts/scan.py \
      --range "origin/${{ github.base_ref }}..HEAD" \
      --fail-on error --no-color
```

- shallow clone 이면 base ref 가 없어 종료 코드 2 가 납니다. `fetch-depth: 0` 이나 base 브랜치 fetch 가 필요합니다.
- 도입 초기에는 `--fail-on never` 로 리포트만 남기고, 로그를 본 뒤 `error` 로 올립니다.
- 의미 판정(`--review`)은 캐시가 있는 로컬에서만 의미가 있습니다. CI 에서는 쓰지 않습니다.
