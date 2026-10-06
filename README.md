# convention-guard

**한국어** · [English](README.en.md)

**바로 가기**: [무엇이 다른가](#무엇이-다른가) · [빠른 시작 (5분)](#빠른-시작-5분) · [팀 레포에 도입하기](#팀-레포에-도입하기) · [스킬](#스킬) · [터미널과 CI](#터미널과-ci) · [더 알아보기](#더-알아보기) · [알려진 한계](#알려진-한계)

AI 코딩 에이전트가 턴을 끝낼 때마다 **에이전트가 쓴 줄**이 팀 컨벤션을 지켰는지 검사하고, 어겼으면 고치게 한 뒤 **고쳐졌는지 다시 검증**하는 Claude Code 플러그인입니다.

`CLAUDE.md` 나 `AGENTS.md` 에 컨벤션을 적어 두어도 긴 세션에서는 잊힙니다. convention-guard 는 에이전트에게 기억을 요구하지 않습니다. 잊더라도 턴이 끝날 때 다시 검사되는 환경을 만듭니다.

에이전트가 디버그 로그를 남긴 채 턴을 끝내려 하면, Stop 훅이 이렇게 막습니다.

```
convention-guard ✖ 차단 — error 1 · warn 0

■ 지적 — 고치거나 기각하세요
✖ error[core/js-no-console]: console 잔여물
  legacy.js:7  console.log(add(1, 2));
  = 안내: 디버그 로그가 남아 있습니다. 제거하거나 팀 로거로 교체하세요.
```

에이전트가 그 줄을 고치고 다시 턴을 끝내면, 같은 범위를 다시 검사해 결과를 알립니다.

```
convention-guard ✔ 재검증 통과 — 고쳐짐 1 · 기각 0
```

같은 파일 1번 줄에 원래 있던 `console.log("legacy")` 는 지적되지 않았습니다. 에이전트가 쓴 줄이 아니기 때문입니다.

## 무엇이 다른가

- **에이전트가 쓴 줄만 봅니다.** 도구 호출마다 전후 내용을 비교해 줄의 출처를 기록합니다. 원래 있던 레거시, 사람이 옆에서 고친 줄, `git pull` 로 들어온 남의 커밋에는 반응하지 않습니다.
- **주석과 문자열은 코드가 아닙니다.** 주석 처리한 `console.log(`, 문자열 안의 `dd(` 는 지적하지 않습니다. tree-sitter 구문 트리로 판정하고, 엔진은 플러그인이 스스로 설치합니다.
- **후보는 위반이 아닙니다.** 정규식은 후보를 좁힐 뿐이고, 판정은 코드를 본 에이전트가 합니다. 오탐은 기각으로 기록되어 그 코드가 그대로인 동안 다시 지적되지 않습니다.
- **판정할 것이 없으면 AI 호출도 없습니다.** N+1·계층 경계처럼 정규식으로 안 되는 규칙만, 후보가 있고 판정 기록이 없을 때 서브에이전트가 함수 하나 분량을 보고 판정합니다. 정규식 신호가 아예 없는 컨벤션(컨트롤러에 비즈니스 로직 금지 등)은 정해 둔 파일에 에이전트가 코드를 추가할 때 함수 단위로 판정합니다.
- **놓친 것은 말합니다.** 수집 훅이 죽었거나 구조를 읽지 못했으면 이름을 붙여 알립니다. 검사하지 못한 것이 통과로 보이지 않습니다.

Laravel·PHP·Blade, Next·React·Nest·JS/TS, Python 규칙 34개가 들어 있고, 팀 규칙을 YAML 로 더할 수 있습니다.

## 빠른 시작 (5분)

빈 체험용 레포에서 차단 → 수정 → 재검증 한 사이클을 직접 봅니다.

**준비물**: Claude Code, `python3` 3.10 이상, git.

```bash
python3 --version    # 3.10 이상인지
```

### 1. 설치

```bash
claude plugin marketplace add develeep/convention-guard
claude plugin install convention-guard@develeep-convention-guard
```

Claude Code 안에서라면 `/plugin marketplace add develeep/convention-guard` 와 `/plugin install convention-guard@develeep-convention-guard` 로 같은 일을 합니다. 설치 범위·팀 전체에 켜기·오프라인 설치는 [설치 문서](docs/guide/ko/installation.md)에 있습니다.

### 2. 체험용 레포 만들기

```bash
mkdir cg-demo && cd cg-demo && git init -q
echo '{"name":"cg-demo","private":true}' > package.json     # JS 레포로 감지됨
printf 'console.log("legacy");\n' > legacy.js                # 원래 있던 레거시 줄
mkdir -p .claude/convention-guard
cat > .claude/convention-guard/config.yaml <<'EOF'
mode: fix                     # 위반이면 턴을 차단 (기본값은 기록만 하는 report)
severity:
  core/js-no-console: error   # 체험용: 경고 규칙을 차단 강도로 올림
EOF
git add -A && git commit -qm init
```

### 3. Claude Code 에게 일 시키기

같은 디렉터리에서 `claude` 를 실행하고 이렇게 요청합니다. 파일 편집 권한을 물으면 허용하세요.

```
legacy.js 맨 아래에 두 수를 더하는 add 함수를 추가하고, add(1, 2) 결과를 console.log 로 출력해 줘. 컨벤션 지적이 나오면 지적대로 고쳐도 돼.
```

### 4. 결과 보기

에이전트가 코드를 쓰고 턴을 끝내려 하면 위에서 본 `✖ 차단` 메시지가 나오고, 에이전트가 새로 쓴 `console.log` 줄을 지운 뒤 `✔ 재검증 통과 — 고쳐짐 1` 로 끝납니다. 1번 줄의 레거시 `console.log` 는 그대로입니다.

첫 세션에는 구조 엔진이 백그라운드로 설치되는 중이라 `구조 엔진 없음 (설치 중)` 이 함께 보일 수 있습니다. 검사는 그대로 돌고, 설치가 끝나면 보이지 않습니다.

다 봤으면 `cd .. && rm -rf cg-demo` 로 지웁니다.

## 팀 레포에 도입하기

체험에서는 설정을 손으로 썼지만, 실제 레포에서는 에이전트에게 맡깁니다. 레포에서 Claude Code 를 열고 **"convention-guard 세팅해줘"** 라고 하세요. `convention-setup` 스킬이 다음을 합니다.

1. 스택·린터·포맷터를 감지하고 적용될 규칙을 보여 줍니다.
2. `.claude/convention-guard/config.yaml` 초안을 `mode: report`(기록만)로 씁니다.
3. 최근 20커밋에서 실제로 몇 건이 걸리는지 재고, 너무 많이 걸리는 규칙과 레거시 디렉터리를 조정합니다.
4. 적용되는 규칙 전부를 `AGENTS.md` 로 내보내, 에이전트가 쓰기 **전에** 알게 합니다.

그다음은 이렇게 갑니다.

- **켜기 전 점검**: "도입 점검해줘" → `convention-readiness` 가 [도입 체크리스트](docs/guide/ko/production-readiness.md)를 자동으로 돌립니다. 팀원 모두에게 켜는 방법도 여기서 확인합니다.
- **2~3주 기록**: `report` 모드는 차단하지 않고 기록만 쌓습니다.
- **튜닝과 전환**: "규칙 정리해줘" → `rule-tune` 이 수정률·기각률로 오탐 규칙을 좁히고, 건강하면 `mode: fix` 로 올리자고 제안합니다.

`.claude/convention-guard/` 의 `config.yaml`, `dismissed.yaml`, `rules/` 는 모두 커밋 대상입니다. 예시: [examples/repo-local/](examples/repo-local/)

## 스킬

평소 말로 요청하면 맞는 스킬이 골라지고, `/convention-guard:<스킬>` 로 직접 부를 수도 있습니다.

| 스킬 | 이럴 때 |
|---|---|
| `convention-setup` | 레포에 처음 도입하거나, 설정을 처음부터 다시 잡을 때 |
| `convention-check` | 훅을 기다리지 않고 지금 검사할 때 (커밋·PR 직전, 브랜치 전체, 레거시 감사) |
| `convention-readiness` | 팀 레포에 켜기 전, 업데이트 직후, `fix` 로 올리기 전 |
| `convention-discover` | CLAUDE.md·PR 리뷰·코드에서 팀 컨벤션을 찾아 규칙 후보로 만들 때 |
| `rule-add` | 반복되는 리뷰 지적을 규칙으로 만들 때 |
| `rule-tune` | 로그가 쌓인 뒤 오탐 규칙을 좁히고 건강한 규칙을 승격할 때 |

스킬마다 하는 일과 사용법: [docs/guide/ko/skills.md](docs/guide/ko/skills.md)

## 터미널과 CI

스킬이 부르는 스크립트는 직접 실행할 수도 있습니다. 같은 파이프라인이라 훅과 판단이 다르지 않습니다.

```bash
CG=$(claude plugin list --json | python3 -c "import json,sys; print(next(p['installPath'] for p in json.load(sys.stdin) if p['id'].startswith('convention-guard@')))")

python3 "$CG/scripts/scan.py" --staged                   # 커밋 직전 검사. 종료 코드 0 통과 / 1 지적 / 2 검사 불가
python3 "$CG/scripts/scan.py" --range origin/main..HEAD  # 브랜치 변경분
python3 "$CG/scripts/detect_stack.py"                    # 무엇이 감지되고 어떤 규칙이 왜 적용되나
```

훅은 각자의 로컬 안전망이고, 팀 전체의 강제는 CI 에서 합니다. GitHub Actions 예시와 모든 스크립트의 옵션은 [docs/guide/ko/cli.md](docs/guide/ko/cli.md)에 있습니다.

## 더 알아보기

| 문서 | 내용 |
|---|---|
| [설치](docs/guide/ko/installation.md) | 요구 사항, 설치 범위, 팀 전체에 켜기, userConfig, 구조 엔진, 업데이트·제거, 3.x 에서 올라오기 |
| [스킬](docs/guide/ko/skills.md) | 스킬 6개와 리뷰어 에이전트의 설명과 사용법 |
| [동작 원리](docs/guide/ko/how-it-works.md) | 줄의 출처 기록, 후보가 되는 조건, 차단과 재검증, 알림 읽기, 기각, 상태와 로그, 한계 |
| [명령](docs/guide/ko/cli.md) | `scan.py` 등 스크립트 옵션 전체, 종료 코드, CI |
| [설정](docs/guide/ko/configuration.md) | 설정 키 전체, mode, 프리셋, 린터 위임, 환경 변수, 설정 오류 |
| [규칙](docs/guide/ko/rules.md) | 규칙 파일 형식, 앵커, 구조 조건, 오버라이드, 프리셋, 번들 규칙 |
| [의미 판정](docs/guide/ko/semantic-review.md) | 서브에이전트 판정 흐름, 컨텍스트 팩, 판정 캐시, 비용 |
| [도입 체크리스트](docs/guide/ko/production-readiness.md) | 실서비스에 켜기 전 확인할 항목 전부 |

플러그인을 고치려는 사람을 위한 문서는 따로 있습니다: [구조](docs/architecture.md), [개발](docs/development.md), [출력 형식](docs/output-format.md), [4.0 설계](docs/design-4.0.md).

> **3.x 에서 올라오나요?** 4.0 은 하위 호환을 끊었습니다. 3.x 의 기각 기록과 판정 캐시를 읽지 않고, 일부 설정 키와 Go 규칙이 빠졌습니다. [설치 문서의 3.x 절](docs/guide/ko/installation.md#3x-에서-올라올-때)을 보세요.

## 알려진 한계

스택은 레포 루트에서 한 번만 판정하므로 모노레포는 경로로 나눠야 하고, 타입 추론이 필요한 판정은 린터의 몫이며, Windows 네이티브는 검증되지 않았습니다. 전체 목록은 [동작 원리의 알려진 한계](docs/guide/ko/how-it-works.md#알려진-한계)에 있습니다.

## 라이선스

MIT
