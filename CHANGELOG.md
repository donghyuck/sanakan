# 변경 이력

## 1.5.0 — 2026-09-22

- 원격 추적 ref/FETCH_HEAD의 commit도 정확한 SHA fetch로 작업공간에 전달한다.
- 각 검증 명령 뒤 HEAD/index/소스 상태를 검사하고 소스 변경을 성공으로 처리하지 않는다.
- stale publication을 needs_revalidation으로 분리하고 개발 호스트의 retry --mode revalidate로 새 generation을 만든다.
- 자동 실행은 Docker backend로 제한하고 로컬 개발 결과의 게시를 차단한다.
- HMAC 인증 packet과 기준 Git bundle을 사용해 서로 다른 private run 저장소 간 export/import를 연결한다.
- 실제 Codex 임시 저장소 실증을 수행했다. Docker 데몬/GitLab 실환경 검증은 미수행이다.

## 1.4.0 — 2026-09-21

- 주기적 이슈 조회와 ready 결과 게시를 분리한 watch/start 및 status/stop/retry CLI를 추가했다.
- issue별 영속 상태·중복 방지·개발 재시도 generation·제한된 게시 재시도·비정상 종료 복구를 구현했다.
- 프로젝트별 브랜치/커밋/MR 템플릿을 검증하고 게시 결과를 원격에서 재확인한다.
- 작업 시작 시 target baseline 고정과 선택적 신뢰 origin fetch를 지원한다.
- Codex 관리 스킬, 플러그인 manifest/launcher 및 runtime 포함 ZIP 빌더를 추가했다. 개인 설치 설정은 변경하지 않는다.
- 실제 계정의 자동화 시작은 수행하지 않았다. 운영 격리와 실제 모델/GitLab 실증은 별도 필요하다.

## 1.3.2 — 2026-09-21

- 로컬 설치·설정과 에이전트 실행·결과 확인을 설명하는 SVG 안내 이미지 두 장을 추가했다.
- README 상단에 이미지, 설정 파일 설명, 복사 가능한 실행 명령과 상태별 안내를 배치했다.
- 현재 지원하는 로컬 fixture 실행을 기준으로 작성했다. 미구현 env 파일 로딩을 지원한다고 표시하지 않는다.

## 1.3.1 — 2026-09-21

- 설치 순서를 기존 로컬 Git 프로젝트 테스트 → GitLab 연동으로 변경했다.
- 로컬 설정/작업 JSON 예시와 기준 commit·만료 설정·실행·결과 확인 가이드를 추가했다.
- 기존 `--issue-fixture`의 실제 모델 실행, GitLab 불필요, 임시 필드와 게시 차단 제약을 명시했다.
- 설치 가이드를 경로 지정·설정·실행·결과 확인의 네 단계로 단순화하고 편집 예시와 문제 해결 표를 추가했다.
- 실행기 코드는 변경하지 않았다.

## 1.3.0 — 2026-09-21

- 프로젝트 목적을 Codex 협업 자동화 코딩 도구로 명시하고 이슈 URL 기반 파일럿 실행기를 추가했다.
- 메인·개발·리뷰를 독립 CLI 세션으로 실행하고 실패 피드백/수정 횟수/검증 정책을 연결했다.
- 프로젝트·작성자·baseline·경로·유효 기간 계약, 단일 호스트 잠금 및 상태 snapshot을 추가했다.
- 별도 게시 환경에서 GitLab commit/branch/Draft MR/reviewer를 생성하고 remote tree와 결과를 재확인한다.
- 이슈/target 변경 차단과 모호한 MR 생성 응답 이후 중복 없는 재시도를 오프라인 검증한다.
- 실제 모델/GitLab 실증과 Webhook/플러그인/댓글 기반 재개는 후속 범위로 명시했다.

## 1.2.0 — 2026-09-21

- 누락된 Git/CI 파일을 복원하고 LICENSE를 배포 목록에 포함했다. 로컬 OMX 상태는 배포에서 제외한다.
- Reviewer의 입력을 collector의 불변 patch 및 독립 checkout으로 통일했다.
- gate에 필수 `--verification-policy` 입력과 verification의 `check_ids` 필드를 추가했다.
  기존 호출자는 보호된 baseline/검증 ID/명령 정책과 새 결과 형식을 제공해야 한다.
- 사람 감독 작업에서 유효한 승인 범위는 진행하도록 공통 지침을 수정했다. 무인 Low 위험 제한은 유지한다.

## 1.1.0 — 2026-09-21

- Git 게시용 문서·템플릿·오프라인 검증 도구로 배포 범위를 명확히 했다.
- 안전성이 확보되지 않은 자동 Push/MR 예시는 기본 차단하고 별도 신뢰 게시기 요건을 문서화했다.
- 새 파일·staged 변경을 보존하는 패치 수집과 fail-closed 상태 검증 도구 및 회귀 테스트를 추가했다.
- 프로젝트별 필수 검증 누락을 실패로 처리하고 프론트 typecheck/test를 포함했다.
- 기존 정책과 병합하는 Issue/MR/commit 템플릿, GitHub·Studio 다중 저장소 안내를 보완했다.
- MANIFEST, SHA256SUMS, 자체 검증기와 게시 체크리스트를 제공한다.

## 1.0 — 2026-09-18

- 사용자 제공 원본: Codex 기반 GitLab 개발 운영 도입 가이드 및 예시 템플릿.
