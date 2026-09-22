# GitHub 프로젝트 지원

Sanakan 1.6.0은 GitHub.com의 이슈 조회·주기적 감시·branch/commit 생성·Draft PR·리뷰 요청을 지원한다.
GitLab 설정은 그대로 사용할 수 있고, provider를 생략하면 기존처럼 GitLab으로 처리한다.
GitHub Enterprise Server, fork PR, team reviewer는 이 버전의 범위 밖이다.

## GitLab과 같은 규칙

- 승인한 작성자의 열린 이슈만 개발한다. GitHub issues API에 섞인 PR 항목은 제외한다.
- 고정 baseline에서 작업하고, 필수 검증·독립 리뷰·형식 정책을 적용한다.
- 자동 게시에는 Docker 실행과 인증된 export/import가 필요하다. local/fixture 결과는 게시하지 않는다.
- 작업 branch를 새로 만든다. 기존 branch를 PATCH하거나 force update하지 않는다.
- 항상 Draft PR을 생성하고, 별도 API로 지정 reviewer에게 리뷰를 요청한다.
- 제목·본문·head/base·Draft 상태·commit·tree·리뷰 요청을 다시 확인해야 published가 된다.
- 리뷰 요청이 거절되면 실패로 남긴다. Draft를 자동 해제하거나 assignee 지정으로 대체하지 않는다.
- 생성 응답이 유실되면 기존 branch/PR/review request부터 조회해 재개한다. 자동 병합은 없다.

GitHub의 Draft와 코드오너 자동 리뷰 요청은 별개의 동작이다.
실제 계정/저장소에서 Draft에 대한 명시적 reviewer 요청이 허용되는지는 실증이 필요하다.
허용되지 않을 경우 원래 정책을 임의로 바꾸지 않고 publish_failed와 API 오류로 보고한다.

## 설정

[GitHub 설정 예시](../examples/runner/github-project.json)를 복사한다.
GitLab 예시와 달라지는 필드는 다음과 같다.

```json
"provider": "github",
"github_url": "https://github.com",
"project_path": "owner/repository",
"project_id": 123456,
"allowed_author_ids": [1234],
"reviewers": ["reviewer-login"]
```

- `project_id`: GitHub 저장소의 숫자 ID. API에서 실제 저장소 ID를 매번 대조한다.
- `allowed_author_ids`: GitHub 이슈 작성자의 숫자 user ID.
- `reviewers`: 사람 리뷰어의 GitHub login. GitLab의 reviewer_ids와 혼용하지 않는다.
- `repo_path`: 이미 로컬에 clone한 대상 프로젝트의 절대 경로.
- 나머지 baseline/target_branch/allowed_paths/checks/automation/execution/만료 설정은 동일하다.
- publication의 `mr_title`, `mr_body` 이름은 호환성을 위해 유지하며 GitHub에서는 PR 제목·본문에 적용한다.

기본 commit 형식이 프로젝트 규칙과 다르면 publication을 수정한다. 예를 들어 studio-api는
`[ai-assisted] fix(scope): ...`와 한국어 Issue/Why/What/Validation 기록을 요구하므로 해당 저장소 지침에 맞춘다.
이 예시를 추가했다고 studio-api의 지침이나 소스를 변경한 것은 아니다.

## 인증과 실행

환경변수 이름은 두 플랫폼에서 같다.

| 실행 주체 | 환경변수 | GitHub 저장소 권한 |
|---|---|---|
| 개발 감시기 | SANAKAN_READ_TOKEN | Metadata/Contents/Issues 읽기 |
| 게시 감시기 | SANAKAN_PUBLISH_TOKEN | Metadata/Issues 읽기, Contents/Pull requests 쓰기 |

대상 저장소로 범위를 제한한 fine-grained token 또는 GitHub App installation token을 사용한다.
실제 저장소 역할/조직 정책/리뷰어 접근 권한에 따라 추가 설정이 필요할 수 있다.
토큰을 URL이나 project.json에 넣지 않는다. API redirect는 따라가지 않는다.

이슈 URL만 플랫폼에 맞게 바뀐다. `--issue-fixture`를 사용할 경우에는 GitHub REST 원문이 아니라
기존 로컬 예시의 내부 형식(iid, project_id, description, state=opened, author.id)을 사용한다.

```sh
python3 -m sanakan run \
  --config /protected/github-project.json \
  --issue https://github.com/owner/repository/issues/123 \
  --runs /var/lib/sanakan-develop
```

주기적 실행은 [자동화 가이드](AUTOMATION.md)와 같다. 서로 다른 개발/게시 private runs,
Docker 이미지와 모델 전용 네트워크, 전달 키/디렉터리를 [실행 경계 가이드](EXECUTION_BOUNDARY.md)에 따라 준비한다.
`start`, `status`, `stop`, `retry`, `export`, `import`도 같은 명령을 사용한다.
GitHub 상태에는 `pr_url`, 공통 `review_url`이 추가된다. 기존 소비자를 위해 `mr_url`도 같은 URL로 유지한다.

## 동작과 제한

GitHub Git Data API로 blob/tree/commit을 만든 뒤 새 ref를 생성한다.
ref 생성 이후 응답이 끊겨도 기존 ref의 commit 메시지·부모·파일 tree를 확인해 재사용한다.
PR 생성과 reviewer 요청도 각각 재조회한다. 이미 리뷰를 제출한 사용자는 재시도 때 다시 알리지 않는다.
PR 목록에서 다른 저장소/fork의 PR을 자신의 결과로 채택하지 않는다.
GitHub가 recursive tree를 truncated로 반환하면 완전한 비교를 할 수 없으므로 게시를 중단한다.

테스트에서는 실제 Git 객체·서명된 전달·상태 흐름을 사용하고 GitHub HTTP 응답을 모의 처리한다.
실제 studio-api/GitHub에 이슈·branch·PR·리뷰 요청은 생성하지 않았다. 인증된 GitHub 실증은 별도 단계다.

공식 계약:
[Issues](https://docs.github.com/en/rest/issues/issues),
[Git trees](https://docs.github.com/en/rest/git/trees),
[Git references](https://docs.github.com/en/rest/git/refs),
[Pull requests](https://docs.github.com/en/rest/pulls/pulls),
[Review requests](https://docs.github.com/en/rest/pulls/review-requests).
