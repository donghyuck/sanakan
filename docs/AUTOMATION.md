# 이슈 등록부터 MR까지 자동으로 실행하기

Sanakan 1.6.0은 GitHub/GitLab 이슈를 주기적으로 확인해 개발·검증·독립 리뷰를 수행하고,
설정한 형식의 작업 브랜치·커밋·Draft MR을 만들어 사람 리뷰를 요청한다.
프로젝트별로 처음 한 번 설정한 후에는 두 감시 프로세스가 작업을 이어받는다.

```text
이슈 등록 → 개발 감시기 → 메인·개발·리뷰 Codex → 검증된 ready 결과
                                                     ↓
                         사람 리뷰 ← Draft MR ← 게시 감시기
```

개발 감시기는 읽기 토큰과 Codex 인증을 사용한다. 게시 감시기는 별도 환경의 쓰기 토큰을 사용하고
모델이나 프로젝트 검증 코드를 실행하지 않는다. 두 프로세스를 하나의 자격증명 환경으로 합치지 않는다.

GitHub를 사용할 때는 [GitHub 가이드](GITHUB.md)의 provider/URL/reviewer 설정을 사용한다.
나머지 자동화·격리·전달 절차는 동일하다.

## 먼저 준비할 실행 경계

[실행 격리와 결과 전달](EXECUTION_BOUNDARY.md)을 먼저 준비한다. 자동 감시는 Docker backend와
서명된 전달 디렉터리/키가 필수이며, 개발·게시 계정은 서로 다른 private runs를 사용한다.
로컬 프로세스 결과는 게시할 수 없다.

## 1. 프로젝트 설정

[자동화 설정 예시](../examples/runner/automation-project.json)를 보호된 위치에 복사한다.
기존 로컬 clone을 `repo_path`로 지정하고 실제 baseline, project/user ID, allowed_paths, checks,
expires_at을 채운다. 기존 AGENTS/CONTRIBUTING/커밋·MR 템플릿을 읽고 publication 규칙에 반영한다.
예시의 만료 시각 0은 실행을 차단하므로 실제 사전 승인 유효 기간으로 바꾼다.

추가된 자동화 설정:

```json
"automation": {
  "poll_seconds": 300,
  "required_labels": [],
  "baseline_mode": "target",
  "fetch_source": false,
  "max_publish_attempts": 3
}
```

- `poll_seconds`: 한 차례 처리가 끝난 후 다음 조회까지 대기하는 초. 위 예시는 5분이다.
- `required_labels`: []이면 허용 작성자의 열린 이슈 전부를 후보로 한다. `["ai:ready"]`이면 그 label이 있는 이슈만 처리한다.
- 작성자 ID allowlist, 열림 상태, 필수 내용, 경로·위험 제한을 다시 확인한다. label만으로 권한을 부여하지 않는다.
- `baseline_mode: target`: 새 작업을 시작할 때 원격 target branch의 SHA를 고정한다. 기존 작업은 고정된 SHA를 유지한다.
- `baseline_mode: pinned`: project.json의 baseline만 사용한다. target이 이동하면 게시가 차단된다.
- `fetch_source: false`: 이미 로컬 clone에 있는 commit만 사용한다. 원격 commit이 없으면 로컬 clone 갱신 후 명시적으로 retry한다.
- `fetch_source: true`: target 모드에서 신뢰된 로컬 clone의 origin을 fetch한다. origin은 설정된 프로젝트의 HTTPS URL과 같아야 하며 URL에 토큰을 넣지 않는다. private 저장소의 Git 읽기 인증은 신뢰된 호스트에 별도로 준비한다.
- `max_publish_attempts`: 게시 오류의 자동 재시도 한도. 개발 실패는 비용을 반복 소모하지 않도록 자동 재등록하지 않는다.

`allowed_paths`는 현재 정확한 파일 목록이다. 새로운 파일/범위가 필요하면 정책을 갱신하고 재검증한다.
`expires_at`은 자동 갱신하지 않는다. 장기 운영에 맞는 승인 기간을 직접 정한다.

## 2. 형식 정책

`publication`에는 네 가지 템플릿을 지정한다. 값은 에이전트가 자유롭게 생성하지 않고 프로그램이 조립한다.

| 필드 | 예시 / 필수 조건 |
|---|---|
| `branch` | `codex/issue-{iid}`. iid 필수, 다른 변수는 불가 |
| `commit` | `[ai-assisted] fix: #{iid} {title}`로 시작하고 본문에 `{issue_url}`, `{verification}` 포함 |
| `mr_title` | `Draft: #{iid} {title}`. Draft 접두사 필수 |
| `mr_body` | 프로젝트 양식. `{issue_url}`, `{verification}`, `{baseline}`, `{patch_sha256}` 필수 |

추가 변수는 `{project_path}`, `{summary}`, `{changed_files}`, `{review_summary}`, `{rollback}`이다.
format 변환/속성 접근/명령 실행은 허용하지 않는다. 예시 파일에 전체 커밋·MR 본문이 있다.
commit 뒤에는 재시도 식별을 위한 Sanakan-Run/Patch-SHA256 항목이 자동 추가된다.
개발 clone에 작업 branch를 먼저 만들고, 게시기는 GitLab Commits API로 같은 이름의 원격 branch/commit을 생성한다.
게시 후 실제 commit message, MR 제목·본문·reviewer·SHA와 파일 tree를 확인한다.

## 3. 개발 감시 시작

도구 루트에서 실행한다. SANAKAN_READ_TOKEN과 Codex 인증을 개발 전용 환경에 준비한다.
SANAKAN_PUBLISH_TOKEN은 이 환경에 제공하지 않는다.

```sh
python3 -m sanakan start --role develop \
  --config /protected/project.json --runs /var/lib/sanakan-develop
```

이 명령은 별도 background 프로세스를 실행한다. 운영 감독 프로그램에서 직접 관리하려면
`start` 대신 `watch`를 실행한다. foreground 실행에서 `--once`를 붙이면 조회/처리 한 번만 수행한다.
컴퓨터가 꺼지거나 잠들면 로컬 프로세스가 계속 동작하지 않는다. 재부팅 자동 시작은 OS 서비스 설정이 필요하다.
설정 변경은 해당 감시기를 중지한 뒤 다시 시작해야 반영된다.

## 4. 게시 감시 시작

모델/개발 프로세스와 분리된 게시 환경에서 SANAKAN_PUBLISH_TOKEN만 제공한다.
동일한 프로젝트 정책과 각 계정의 소스 clone, 서로 다른 private run 저장소가 필요하다.
공유 디렉터리에는 signed packet만 전달하며, jobs.json이나 내부 작업공간은 공유하지 않는다.

```sh
python3 -m sanakan start --role publish \
  --config /protected/project.json --runs /var/lib/sanakan-publish
```

두 감시기가 실행되면 이슈마다 수동 run/publish 명령을 입력하지 않는다.
게시 단계에서 이슈 내용/label/작성자/target SHA/정책이 달라졌으면 게시를 차단한다.
API 응답이 유실돼도 기존 branch/MR을 조회하고 같은 결과를 재사용한다. 자동 병합은 하지 않는다.

## 5. 상태 확인·중지·재시도

아래 --runs는 조회/관리하려는 계정의 private runs로 바꾼다. 재검증은 개발 계정에서
`retry --iid 123 --mode revalidate`로 요청한다. 이전 결과의 게시만 반복하지 않는다.

```sh
python3 -m sanakan status --config /protected/project.json --runs /var/lib/sanakan
python3 -m sanakan stop --role all --config /protected/project.json --runs /var/lib/sanakan
python3 -m sanakan retry --iid 123 --config /protected/project.json --runs /var/lib/sanakan
```

- status의 `running`은 PID 숫자만이 아니라 실제 역할 잠금으로 확인한다.
- stop은 새 작업/다음 단계를 멈춘다. 현재 명령이 끝나거나 timeout되기 전까지 즉시 종료되지는 않는다.
- `running: false`가 된 뒤 정지 완료로 판단한다. 게시가 중간에 멈추면 생성된 branch를 삭제하지 않고 다음 게시 때 확인한다.
- 개발 retry는 generation을 올려 새 작업공간에서 수행하고 이전 결과를 보존한다.
- 게시 retry는 같은 검증 patch를 사용한다. 정책·이슈가 달라진 오류를 우회하는 명령이 아니다.
- 이미 published인 작업은 다시 개발하지 않는다. 사람 리뷰 댓글에 따른 후속 수정은 현재 자동 수신하지 않는다.

개발 상태는 queued → developing → ready → handed_off이며, 게시 상태는 import된 ready → publishing → published다.
needs_human/failed/stopped/interrupted는 사람이 기록을 확인하고 retry해야 한다.
publish_retry는 다음 조회 때 재시도하고, 한도에 도달하면 publish_failed로 멈춘다.
비정상 종료 후 개발 중이던 작업은 자동으로 다시 모델을 실행하지 않는다. ready 기록이 있으면 복구하고,
그 외에는 interrupted로 표시한다. 게시 중이던 작업은 원격 결과 조회를 통해 복구한다.

## Codex에서 관리

`plugins/sanakan/skills/sanakan-manage` 스킬은 이 CLI를 사용한다. 예를 들어
“이 프로젝트 자동 개발을 시작해줘”, “상태를 보여줘”, “123번 실패 원인을 확인하고 재시도해줘”라고 요청할 수 있다.
스킬은 먼저 실제 설정/자격증명 환경을 확인한다. 플러그인 설치만으로 감시기를 시작하지 않는다.

배포용 스킬/CLI runtime ZIP은 다음처럼 생성한다.

```sh
python3 tools/build_plugin.py --output /tmp/sanakan-plugin.zip
```

ZIP에는 manifest·스킬·관리 launcher·runtime이 함께 들어간다. source 개발 중에는
`python3 plugins/sanakan/scripts/manage.py --help`로 호출할 수 있다.
개인 Codex 설정과 marketplace는 이 저장소 작업으로 자동 변경하지 않는다.
필요한 환경에 플러그인을 설치/등록한 뒤 새 Codex 작업에서 스킬을 사용한다.
MCP 서버는 포함하지 않는다. 이 버전은 스킬이 CLI를 호출하는 구조다.

## 검증 범위와 운영 전제

오프라인 통합 테스트에서 이슈 조회 → 실제 임시 Git 변경 → 검증 → MR 모의 생성,
중복 방지·수정 반복·재시도·중지·재시작·형식 검사를 확인한다. 실제 Codex 로컬 fixture는 실증했다. Docker 실행과 실제 GitLab/알림/CI는 별도 실증이 필요하다.
프로세스 환경 필터와 clone만으로 같은 UID의 파일/네트워크 접근을 차단할 수 없다.
실제 운영은 개발·검증 sandbox와 보호된 정책/증거 저장소를 준비해야 한다.
다중 호스트 분산 잠금, 토큰 비용 상한, 이슈 댓글 자동 답변 및 자동 병합은 제공하지 않는다.
