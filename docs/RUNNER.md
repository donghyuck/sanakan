# Sanakan 실행기 사용법

이슈 URL을 입력받는 Codex 자동화 코딩 파일럿이다. 전체 목표와 상태는 [실행 명세](EXECUTION_SPEC.md)를 따른다.
Webhook 서버와 플러그인은 아직 포함하지 않는다.

## 준비

- Linux/macOS, Python 3.11+, Git, Bash와 신뢰된 로컬 소스 복제본.
- 실제 에이전트 실행에는 인증된 Codex CLI가 필요하다. 로컬에서 0.139.0의 exec 도움말을 확인했다.
- 개발 전용 계정/컨테이너에 Codex 인증만 제공하고 GitLab 쓰기 토큰/운영 비밀을 두지 않는다.
  사용자 config를 무시해 실행하지만 프로젝트 설정과 기존 AGENTS는 검토한 baseline이어야 한다.
- 검증은 자격증명 없는 별도 실행 환경에서 수행하도록 호스트를 준비한다. 현재 프로세스 환경변수
  필터링은 HOME의 credential 파일, 네트워크, 같은 UID의 파일 접근까지 격리하지 않는다.
- 호스트가 보호하는 설정·run 저장소와 별도 게시 환경을 사용한다. 패키지 자체를 worker checkout에 설치해 실행하지 않는다.

## 프로젝트 계약

[설정 예시](../examples/runner/project.json)를 보호된 위치에 복사해 모든 값을 실제 프로젝트에 맞춘다.

- `gitlab_url`: HTTPS origin. 하위 경로 설치 GitLab은 현재 미지원.
- `project_path`/`project_id`: 허용 프로젝트의 경로/숫자 ID. 이슈 URL 및 응답을 모두 확인한다.
- `repo_path`: 신뢰된 소스 복제본 절대 경로. 기준 commit이 이미 존재해야 하며 자동 fetch하지 않는다.
- `baseline`: 승인된 전체 commit SHA. 게시 시 target branch가 이 SHA와 같아야 한다.
- `allowed_author_ids`/`reviewer_ids`: 자동 실행을 허용한 작성자와 최종 사람 리뷰어의 숫자 ID.
- `allowed_paths`: 정확한 상대 파일 경로. glob/디렉터리 허용 목록은 미지원.
- `checks`: 고유 ID와 argv 배열. 셸 문자열을 자동 실행하지 않는다. 프로젝트에 필요한 검증을 모두 명시한다.
- `max_attempts`: 1~5. 매 attempt마다 메인·개발·검증·필요 시 리뷰를 실행한다.
- `timeout_seconds`: 각 모델/검증 프로세스 제한, 1~3600초. 토큰 비용 한도는 아직 제공하지 않는다.
- `max_patch_bytes`: 수집 후 허용 patch 크기.
- `expires_at`: 사전 승인 만료 Unix 초. 예시의 0은 의도적으로 실행을 차단하므로 실제 만료 시각으로 바꾼다.

설정은 이슈가 제공하는 파일이 아니다. 운영자가 검토한 설정으로 허용 범위를 결정한다.
현재 target 설정/승인 범위를 바꾸면 이전 작업을 계속 게시할 수 없다.

## 1. 이슈 개발 실행

도구 저장소 루트에서 실행한다. 읽기 토큰은 비밀 관리 도구로 `SANAKAN_READ_TOKEN`에 주입한다.
명령 인자, 설정 JSON이나 이슈에는 토큰을 넣지 않는다.

```sh
python3 -m sanakan run \
  --config /protected/project.json \
  --issue https://gitlab.example.com/team/project/-/issues/123 \
  --runs /var/lib/sanakan/runs
```

Codex CLI가 메인(read-only)·개발(workspace-write)·리뷰(read-only)를 별도 ephemeral 세션으로 실행한다.
각 세션에 host context로 이슈/triage/검증 정책/피드백을 전달한다. 기존 AGENTS는 읽되 자동 수정하지 않는다.
모델 최종 JSON은 schema 검증을 거친다. 테스트는 별도 clone에서 수행하고 리뷰에는 새 clone을 제공한다.
`ready`이면 해당 patch가 독립 검증과 gate를 통과했다는 뜻이다. 아직 MR은 생성하지 않는다.

`--issue-fixture /protected/issue.json`으로 API 읽기를 대체할 수 있다.
이 옵션도 실제 Codex를 실행하며 모델 인증이 필요하다. fixture 실행 결과는 게시할 수 없다.
외부 모델 없이 확인하려면 아래 오프라인 통합 테스트를 사용한다.

## 2. 별도 환경에서 게시

보호된 도구/동일 설정/검증 증거와 신뢰된 baseline 소스를 게시 환경에 제공한다.
게시 전용 토큰은 비밀 관리 도구로 `SANAKAN_PUBLISH_TOKEN`에만 주입한다.
개발 프로세스가 종료한 후 신뢰된 작업 스케줄러가 이 단계를 실행하도록 연결할 수 있다.

```sh
python3 -m sanakan publish \
  --config /protected/project.json \
  --issue https://gitlab.example.com/team/project/-/issues/123 \
  --runs /var/lib/sanakan/runs
```

게시기는 gate를 다시 검사하고 이슈가 수정/종료됐거나 baseline이 이동하면 중단한다.
검증된 patch를 별도 checkout에 적용한 뒤 파일 bytes를 GitLab Commits API로 전송한다.
`codex/issue-123` branch에 하나의 commit을 만들고 Draft MR 생성 및 reviewer 지정을 수행한다.
프로젝트 코드나 테스트를 게시 토큰으로 실행하지 않는다. 기존 branch가 다른 작업이면 중단한다.
GitLab API의 commit 생성은 git push 대신 수행하는 저장소 쓰기 작업이다.

생성 뒤 remote tree와 commit 부모, MR SHA/target/reviewer/Draft 상태를 다시 확인한다.
네트워크 오류 뒤 같은 publish를 다시 실행하면 기존 결과부터 조회한다. 병합·force push는 없다.

## 결과와 중단

run 디렉터리에는 `state.json`, 설정/이슈 snapshot, attempt별 모델 결과·patch·검증 로그가 남는다.
로그에는 소스/이슈/모델 출력이 들어갈 수 있으므로 접근 권한과 보관 기간을 관리한다.
stdout에는 상태 JSON과 collector/gate 진행 메시지가 출력된다.
종료 코드 0은 ready/published, 2는 실패 또는 사람 확인 필요다.

정보 부족 시 questions가 state에 기록된다. 이슈 댓글 자동 작성 및 답변 수신은 아직 없다.
프로세스가 중간에 종료된 상태는 재실행해도 자동 복구하지 않는다. 기존 기록을 점검한 후
새 run root에서 명시적으로 다시 실행한다. 같은 이슈의 기존 branch/MR은 게시 단계에서 재확인한다.
여러 호스트에서 서로 다른 run 저장소를 쓰는 분산 실행은 지원하지 않는다.

## 오프라인 검증

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_runner.py -v
```

실제 임시 Git 저장소와 검증 프로세스를 사용하고 모델/GitLab 응답만 모의 처리한다.
따라서 이 테스트 통과는 실제 모델 품질, GitLab 권한, HTTPS, 컨테이너 격리 검증이 아니다.

공식 계약: [Codex exec](https://learn.chatgpt.com/docs/non-interactive-mode),
[GitLab Issues API](https://docs.gitlab.com/api/issues/),
[Commits API](https://docs.gitlab.com/api/commits/),
[Merge requests API](https://docs.gitlab.com/api/merge_requests/).
