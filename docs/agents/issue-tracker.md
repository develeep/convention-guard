# 이슈 트래커: GitHub

이 레포의 이슈와 스펙은 GitHub 이슈로 둔다. 모든 작업은 `gh` CLI 로 한다.

## 관례

- **이슈 만들기**: `gh issue create --title "..." --body "..."`. 여러 줄 본문은 heredoc 을 쓴다.
- **이슈 읽기**: `gh issue view <번호> --comments`. 코멘트는 `jq` 로 거르고 라벨도 함께 가져온다.
- **이슈 목록**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` 에 `--label`·`--state` 필터를 붙인다.
- **코멘트 달기**: `gh issue comment <번호> --body "..."`
- **라벨 붙이기 / 떼기**: `gh issue edit <번호> --add-label "..."` / `--remove-label "..."`
- **닫기**: `gh issue close <번호> --comment "..."`

레포는 `git remote -v` 로 정한다. 클론 안에서 실행하면 `gh` 가 알아서 찾는다.

## 트리아지 대상으로서의 PR

**PRs as a request surface: no.** _(이 레포가 외부 PR 을 기능 요청으로 다룬다면 `yes` 로 바꾼다. `/triage` 가 이 플래그를 읽는다.)_

`yes` 이면 PR 도 이슈와 같은 라벨·상태로 다루고, `gh pr` 명령을 쓴다:

- **PR 읽기**: `gh pr view <번호> --comments`, diff 는 `gh pr diff <번호>`.
- **트리아지할 외부 PR 목록**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` 에서 `authorAssociation` 이 `CONTRIBUTOR`·`FIRST_TIME_CONTRIBUTOR`·`NONE` 인 것만 남긴다(`OWNER`/`MEMBER`/`COLLABORATOR` 는 뺀다).
- **코멘트 / 라벨 / 닫기**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub 은 이슈와 PR 이 번호 공간 하나를 같이 쓰므로 `#42` 만으로는 어느 쪽인지 모른다. `gh pr view 42` 로 먼저 보고, 아니면 `gh issue view 42` 로 본다.

## 스킬이 "이슈 트래커에 올려라"라고 하면

GitHub 이슈를 만든다.

## 스킬이 "관련 티켓을 가져와라"라고 하면

`gh issue view <번호> --comments` 를 실행한다.

## 길찾기(wayfinding) 작업

`/wayfinder` 가 쓴다. **지도(map)** 는 이슈 하나이고, 그 **자식(child)** 이슈가 티켓이다.

- **지도**: `wayfinder:map` 라벨을 단 이슈 하나. 본문에 Notes / Decisions-so-far / Fog 를 둔다. `gh issue create --label wayfinder:map`.
- **자식 티켓**: GitHub 하위 이슈(sub-issue)로 지도에 연결한 이슈(하위 이슈 엔드포인트에 `gh api`). 하위 이슈를 쓸 수 없으면 지도 본문의 작업 목록에 자식을 넣고 자식 본문 맨 위에 `Part of #<지도>` 를 적는다. 라벨: `wayfinder:<종류>` (`research`/`prototype`/`grilling`/`task`). 맡으면 진행하는 개발자에게 할당한다.
- **막힘(blocking)**: GitHub 의 **기본 이슈 의존성**이 정식 표현이다(UI 에 보인다). 간선 추가: `gh api --method POST repos/<owner>/<repo>/issues/<자식>/dependencies/blocked_by -F issue_id=<막는-이슈-db-id>`. `<막는-이슈-db-id>` 는 숫자 **데이터베이스 id** 다(`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, `#번호`나 `node_id` 가 _아니다_). GitHub 은 `issue_dependencies_summary.blocked_by` (열린 막는 이슈만, 실시간 관문)를 알려준다. 의존성을 쓸 수 없으면 자식 본문 맨 위에 `Blocked by: #<n>, #<n>` 줄을 둔다. 막는 이슈가 모두 닫히면 막힘이 풀린다.
- **전선(frontier) 조회**: 지도의 열린 자식을 나열하고(`gh issue list --state open`, 지도의 하위 이슈 / 작업 목록으로 범위를 한정), 열린 막는 이슈가 있거나(`issue_dependencies_summary.blocked_by > 0`, 또는 `Blocked by` 줄의 열린 이슈) 담당자가 있는 것은 뺀다. 지도 순서상 첫 번째를 고른다.
- **맡기**: `gh issue edit <n> --add-assignee @me`. 세션의 첫 쓰기 작업이다.
- **해결**: `gh issue comment <n> --body "<답>"` → `gh issue close <n>` → 지도의 Decisions-so-far 에 맥락 포인터(요지 + 링크)를 덧붙인다.
