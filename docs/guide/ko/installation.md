# 설치

[README](../../../README.md) · **한국어** · [English](../en/installation.md)

## 목차
- 요구 사항
- 설치하기
- 팀 전체에 켜기
- 설치할 때 고르는 값 (userConfig)
- 구조 엔진
- 설치 위치와 데이터 디렉터리
- 업데이트와 제거
- 3.x 에서 올라올 때

## 요구 사항

| 항목 | 조건 | 확인 |
|---|---|---|
| Claude Code | 플러그인을 지원하는 버전 | `claude --version` |
| Python | 3.10 이상이 `python3` 로 실행됨 | `python3 --version` |
| git | 검사할 프로젝트가 git 작업 트리 | `git rev-parse --show-toplevel` |
| 네트워크 | 구조 엔진을 처음 받을 때 한 번 (`files.pythonhosted.org`, 약 1.5MB) | 오프라인이면 [구조 엔진](#구조-엔진) 참고 |

훅은 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/..."` 로 실행됩니다. macOS Command Line Tools 의 `python3` 처럼 3.9 인 경우가 있으니 먼저 확인하세요. 3.9 이하면 훅이 필요한 버전을 알려 주고 검사하지 않습니다.

Windows 네이티브(WSL 이 아닌)는 검증되지 않은 환경입니다. `python3` 가 없거나 Microsoft Store 스텁이면 훅이 돌지 않습니다. WSL 에서 쓰거나, 훅 대신 `scan.py` 와 CI 로 운영하세요.

## 설치하기

세 가지 방법이 있고, 결과는 같습니다.

**Claude Code 안에서** (처음이라면 이 방법):

```
/plugin marketplace add develeep/convention-guard
/plugin install convention-guard@develeep-convention-guard
```

설치 중에 [userConfig](#설치할-때-고르는-값-userconfig) 를 묻습니다. 기본값 그대로 두면 됩니다.

**터미널에서**:

```bash
claude plugin marketplace add develeep/convention-guard
claude plugin install convention-guard@develeep-convention-guard            # 기본 범위: user
claude plugin install convention-guard@develeep-convention-guard --scope local   # 이 레포에서만
```

터미널 설치는 userConfig 를 묻지 않고 `3 userConfig options not yet set` 이라고 알립니다. 비워 두면 플러그인 기본값(`mode: report`)으로 동작합니다. 값을 정하려면 `--config report_only=true` 처럼 설치할 때 넘기거나, Claude Code 에서 `/plugin configure convention-guard@develeep-convention-guard` 를 실행하세요.

**로컬 체크아웃으로 시험** (플러그인을 고치거나 설치 없이 써 볼 때):

```bash
git clone https://github.com/develeep/convention-guard
claude --plugin-dir ./convention-guard
```

설치가 끝나면 **Claude Code 세션을 새로 시작**하세요. 훅과 스킬은 세션을 시작할 때 읽힙니다.

설치 범위:

| 범위 | 적용 대상 | 기록 위치 |
|---|---|---|
| `user` | 내 모든 프로젝트 | `~/.claude/settings.json` |
| `project` | 이 레포를 여는 모든 사람 (커밋) | `<레포>/.claude/settings.json` |
| `local` | 이 레포, 나만 | `<레포>/.claude/settings.local.json` |

## 팀 전체에 켜기

`user`·`local` 범위로만 켜면 **나만** 검사됩니다. 팀원 모두에게 켜려면 레포의 `.claude/settings.json` 에 아래를 넣고 커밋합니다. 팀원이 이 레포에서 Claude Code 를 열면 마켓플레이스 추가와 설치를 안내받습니다.

```json
{
  "enabledPlugins": { "convention-guard@develeep-convention-guard": true },
  "extraKnownMarketplaces": {
    "develeep-convention-guard": {
      "source": { "source": "github", "repo": "develeep/convention-guard" }
    }
  }
}
```

팀 설정(모드, 규칙 강도, 제외 경로)은 별도로 `.claude/convention-guard/config.yaml` 에 두고 커밋합니다. 만드는 방법은 [skills.md 의 convention-setup](skills.md#convention-setup--도입) 을 보세요.

켜기 전에 이 레포에서 정말 의도대로 도는지 확인하려면 [도입 체크리스트](production-readiness.md)를 `convention-readiness` 스킬로 돌립니다.

## 설치할 때 고르는 값 (userConfig)

| 키 | 기본값 | 효과 |
|---|---|---|
| `report_only` | `true` | `true` 면 `mode: report`(기록만), `false` 면 `mode: fix`(차단) |
| `semantic_review` | `false` | 의미 판정(convention-reviewer 서브에이전트)을 켭니다 |
| `log_dir` | (비움) | 발동 로그 `firings.jsonl` 위치. 비우면 플러그인 데이터 디렉터리 |

레포의 `config.yaml` 에 같은 키(`mode`, `semantic_review.enabled`)가 있으면 **레포 설정이 이깁니다.** 개인 설정으로 팀 표준을 조용히 낮출 수 없게 하기 위해서입니다.

`log_dir` 에는 레포 밖의 절대 경로를 쓰세요. `./logs` 같은 상대 경로는 각 레포 안으로 풀려 로그가 레포마다 흩어지고 git 에 잡힙니다.

전체 설정 키는 [configuration.md](configuration.md)에 있습니다.

## 구조 엔진

주석·문자열 안의 코드를 위반으로 보지 않으려면 구문 트리가 필요합니다. convention-guard 는 tree-sitter 휠을 스스로 받아 설치합니다(venv·pip 를 쓰지 않음).

- **언제**: 세션이 시작될 때(SessionStart 훅, 백그라운드), Stop 이 엔진을 필요로 하는데 없을 때(백그라운드), `engine.py ensure` 를 직접 실행할 때.
- **무엇을**: `scripts/lib/engine/lock.json` 에 고정된 휠만 받고 sha256 이 맞지 않으면 거부합니다.
- **설치 전·실패 시**: 검사는 그대로 돌고, 구조 조건을 확인하지 못한 후보를 걸러 내지 않은 채 `구조 엔진 없음 (사유)` 로 알립니다. 통과로 처리하지 않습니다.

```bash
python3 "$CG/scripts/engine.py" status    # 설치됐는지, 어디에
python3 "$CG/scripts/engine.py" ensure    # 지금 설치하고 끝날 때까지 기다림 (CI 용)
```

`$CG` 는 플러그인 설치 경로입니다. [아래](#설치-위치와-데이터-디렉터리)에서 구합니다.

오프라인 환경이면 `lock.json` 에 적힌 휠 파일을 한 디렉터리에 모아 두고 `CONVENTION_GUARD_WHEELS=<그 디렉터리>` 로 `ensure` 를 실행합니다. sha256 검사는 같습니다. musl aarch64 와 free-threaded Python 에는 휠이 없어 엔진 없이 돕니다 (`구조 엔진 없음 (미지원 플랫폼)`).

## 설치 위치와 데이터 디렉터리

스킬은 `${CLAUDE_PLUGIN_ROOT}` 로 스크립트를 부르므로 경로를 몰라도 됩니다. 터미널에서 스크립트를 직접 실행할 때만 설치 경로가 필요합니다. 경로는 버전마다 바뀌므로 외우지 말고 구하세요.

```bash
CG=$(claude plugin list --json | python3 -c "import json,sys; print(next(p['installPath'] for p in json.load(sys.stdin) if p['id'].startswith('convention-guard@')))")
echo "$CG"    # 예: ~/.claude/plugins/cache/develeep-convention-guard/convention-guard/4.1.0
```

`--plugin-dir` 로 쓰는 경우에는 그 체크아웃 경로가 `$CG` 입니다.

| 위치 | 내용 |
|---|---|
| `$CG` | 플러그인 코드 (스크립트, 규칙, 스킬). 손대지 않습니다 |
| `~/.claude/plugins/data/convention-guard-develeep-convention-guard/` | 훅의 데이터 디렉터리(`CLAUDE_PLUGIN_DATA`): 상태 저장소 `convention-guard.db`, 구조 엔진 `engine/`, 발동 로그 `firings.jsonl` |
| `<레포>/.claude/convention-guard/` | 팀 설정 `config.yaml`, 기각 기록 `dismissed.yaml`, 레포 전용 규칙 `rules/`. 커밋 대상 |

터미널에서 직접 실행한 스크립트는 `CLAUDE_PLUGIN_DATA` 가 없으면 `$XDG_CACHE_HOME/convention-guard`(없으면 `~/.cache/convention-guard`)를 씁니다. 훅과 **다른 디렉터리**입니다. 훅이 쌓은 로그나 판정을 터미널에서 보려면 앞에 붙이세요.

```bash
CLAUDE_PLUGIN_DATA=~/.claude/plugins/data/convention-guard-develeep-convention-guard \
  python3 "$CG/scripts/log_report.py" --repo .
```

## 업데이트와 제거

```bash
claude plugin update convention-guard@develeep-convention-guard      # 적용하려면 세션 재시작
claude plugin disable convention-guard@develeep-convention-guard     # 끄기 (설치는 유지)
claude plugin uninstall convention-guard@develeep-convention-guard   # 제거
```

Claude Code 안에서는 `/plugin` 화면에서 같은 일을 합니다. 팀 전체에 켰다면 `.claude/settings.json` 의 `enabledPlugins` 도 고칩니다.

당장 차단만 멈추고 싶으면 제거하지 말고 레포 `config.yaml` 에 `mode: report` 를 두세요. 레포에 남는 것은 `.claude/convention-guard/` 뿐이고, 상태와 캐시는 위 데이터 디렉터리와 `~/.cache/convention-guard` 를 지우면 정리됩니다.

## 3.x 에서 올라올 때

4.0 은 하위 호환을 끊었습니다. 이관 도구는 없습니다.

- 3.x 의 `dismissed.yaml`(`version: 4` 가 없는 파일)은 적용되지 않고 경고가 납니다. 기각을 다시 기록하세요.
- 판정 캐시와 세션 상태는 읽지 않습니다. 처음부터 다시 쌓입니다.
- 설정의 `scope.base_ref`·`collect.edit_tools` 는 지우세요. 남아 있으면 `알 수 없는 설정 … (무시)` 경고가 납니다. 브랜치 전체를 보려면 `scan.py --range <base>..HEAD` 를 씁니다.
- Go 규칙·프리셋은 빠졌습니다.
