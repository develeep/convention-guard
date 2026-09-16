---
name: convention-check
description: 훅을 기다리지 않고 지금 컨벤션 규칙을 실행해 결과를 보여주고 고칩니다. "컨벤션 검사해줘", "규칙 위반 있는지 봐줘", "PR 올리기 전에 확인", "이 브랜치 검사", "레거시 전수조사", 커밋·PR 직전 점검, 특정 파일만 검사할 때 사용하세요.
---

# 컨벤션 규칙 수동 실행

Stop 훅과 **같은 엔진**을 씁니다. 수동 실행과 자동 실행의 결과가 다르면
아무도 안 믿게 되므로 로직을 공유합니다.

## 무엇을 검사할지 먼저 정하기

사용자의 말에서 범위를 고르세요. 애매하면 워킹 트리(기본)로 시작하고, 결과를 보여준 뒤
범위를 넓힐지 물으세요.

```bash
P="${CLAUDE_PLUGIN_ROOT}/scripts/scan.py"

python3 "$P" --no-color                       # 워킹 트리 (기본)
python3 "$P" --staged --no-color              # 커밋 직전
python3 "$P" --range main..HEAD --no-color    # PR 올리기 전 / 브랜치 전체
python3 "$P" --files app/X.php --no-color     # 지정 파일 전체
python3 "$P" --all --no-color                 # 레포 전수조사 (레거시 감사)
python3 "$P" --base-ref auto --no-color       # 세션 중 커밋한 변경까지 함께
```

범위별 성격이 다릅니다.

| 범위 | 앵커 | 언제 |
|---|---|---|
| 워킹 트리 / staged / range | 변경분만 | 평소. 레거시는 안 나옵니다 |
| `--files` | 파일 전체 | 그 파일을 리팩터링할 때 |
| `--all` | 전부 (모든 파일을 새 파일로 취급) | 도입 전 감사, 레거시 규모 파악 |

**`--all` 은 부재 검사까지 전부 적용되어 결과가 많습니다.** 요청받았을 때만 쓰고,
결과가 수십 건이면 전부 나열하지 말고 규칙별로 집계해서 보여주세요.

`--base-ref <ref>` 는 워킹 트리 검사에만 붙습니다. HEAD diff 와 base diff 를 합집합으로
보므로, 세션 중에 커밋해버린 변경도 계속 검사 대상에 남습니다. `auto` 면 `origin/HEAD`
를 먼저 물어보고 없을 때만 main/master 를 추측합니다.

유용한 옵션: `--severity error` (심각한 것만), `--rule <일부 문자열>` (한 규칙만),
`--no-lint` (린터 생략, 빠름), `--json` (집계·가공용),
`--no-dismiss` (기각 기록을 무시하고 전부 보기 — 무엇이 억제되어 있는지 확인할 때).

## 결과를 다루는 법

**출력을 그대로 붙여넣지 마세요.** 읽고 판단한 뒤 정리해서 전달합니다.

1. **오탐을 먼저 걸러내세요.** 정규식이 좁힌 "후보"이지 확정이 아닙니다.
   해당 파일을 `Read` 로 열어 실제 위반인지 확인하세요. 오탐이면 사용자에게
   "이건 오탐"이라고 말하고, 반복되면 규칙 조건을 좁히자고 제안하세요.
2. **오탐은 말로 끝내지 말고 기록하세요.** 채팅에만 남긴 판단은 로그에서
   "안 고침"과 구분되지 않아, 나중에 `rule-tune` 이 건강한 규칙을 오탐으로 읽습니다.

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dismiss.py" \
     --rule core/php-line-too-long \
     --file app/Http/Controllers/OrderController.php \
     --line 84 --reason "체이닝을 끊으면 가독성이 더 나빠짐"
   ```

   기록은 `<repo>/.claude/convention-rules/dismissed.yaml` 에 남고, 커밋해서 팀과
   공유하는 파일입니다. 지문은 줄 번호가 아니라 **그 코드**라서 위쪽에 줄이 추가돼도
   억제가 유지되고, 그 코드 자체가 바뀌면 다시 지적됩니다. 그 파일에서 규칙 전체를
   끄려면 `--whole-file`, 기록 목록은 `--list`. 위치가 지금 걸리지 않으면 기각을
   거부합니다 — 코드가 이미 바뀐 것이므로 기각할 것이 없습니다.
3. **린터 실패는 확정입니다.** 맨 위에 나오면 그것부터 처리하세요.
4. **수정은 허락을 받고 하세요.** 사용자가 "고쳐줘"라고 하지 않았다면 보고만 합니다.
   고칠 때는 `error` 부터, 한 번에 한 규칙씩, 각 수정 후 재검사하세요.
5. **semantic 규칙은 이 명령으로 검사되지 않습니다.** 요약 줄에 개수가 나옵니다.
   N+1 이나 계층 경계까지 보려면 직접 코드를 읽고 판단해야 한다고 알려주세요.

## 아무것도 안 나올 때

지적 0건이면 그대로 보고하고 끝내세요. 억지로 찾아내려고 `--all` 로 범위를 넓히지 마세요.
변경분이 깨끗하다는 게 맞는 답입니다.

규칙이 하나도 적용되지 않았다면(요약의 "적용" 수가 0) 스택 감지 실패입니다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check.py" --explain
```

## CI 에 넣기

종료 코드로 파이프라인을 세울 수 있습니다.

```yaml
- run: |
    python3 plugins/convention-guard/scripts/scan.py \
      --range origin/${{ github.base_ref }}..HEAD \
      --fail-on error --no-color
```

`--fail-on` 은 `error`(기본) / `warn` / `info` / `never`. 도입 초기에는 `never` 로
리포트만 남기다가, 로그가 쌓이면 `error` 로 올리세요.
