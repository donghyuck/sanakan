# 변경 이력

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
