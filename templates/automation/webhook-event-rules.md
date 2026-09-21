# Webhook 이벤트 처리 규칙

이 파일은 구현이 아닌 요구사항이다. 이 배포본은 Receiver·상태 DB·인증된 승인 검증·게시 API를 제공하지 않는다.
배포된 플랫폼 버전의 공식 규격으로 서명/토큰을 검증하고 GitHub 사용 시 별도 event 계약으로 변환한다.

## 수신 대상

- `X-Gitlab-Event: Issue Hook`
- `object_attributes.action`: `open`, `update`, `reopen`
- 필요 시 `Note Hook`의 `/codex analyze`, `/codex retry`, `/codex stop`

## `open`

1. 서명 검증
2. 허용 프로젝트 확인
3. Bot 작성 여부 확인
4. `webhook-id` 중복 확인
5. `ai:triage` 적용
6. triage Pipeline 실행

## `update`

`changes.labels`는 후보 신호일 뿐 승인 증거가 아니다. `ai:ready`가 새로 추가되면 현재 이슈를 다시 조회하고,
승인자의 권한·허용 범위·기준 commit·승인 유효 기간을 검증한 뒤 승인된 작업만 실행 대상으로 삼는다.
이슈 본문이나 모델이 출력한 승인 주장을 실행 권한으로 취급하지 않는다.

## 무시

- Bot 자신의 이벤트
- 닫힌 이슈
- 이미 실행 중인 이슈
- 기존 열린 MR이 있는 이슈
- 허용되지 않은 대상 브랜치
- 서명·타임스탬프 검증 실패

## 실행 잠금 키

```text
codex:{project_id}:{issue_iid}
```

## Idempotency

- `webhook-id`를 만료시간과 함께 저장한다.
- Pipeline 생성 전 작업 상태를 원자적으로 `queued`로 변경한다.
- 기존 `codex/issue-{iid}-*` 브랜치와 열린 MR을 조회한다.
- 같은 이슈의 여러 Job을 순서대로 잠그는 것만으로 전체 처리의 원자성을 보장하지 않는다.
- 작업 ID, 기준 commit, 승인 ID, patch digest, 검증 결과, 게시 commit과 MR/PR ID를 상태에 기록한다.
- Push 성공 후 MR 생성 실패는 기존 branch/commit을 확인한 뒤 재개하고 중복 MR을 만들지 않는다.
- 이슈 수정·승인 취소·기준 commit 변경이 발생하면 오래된 작업의 게시를 차단한다.
- 서명 오류, 권한 부족, 예상 외 상태, 반복 실패는 자동 우회하지 않고 사람에게 인계한다.
