# Sanakan 1.3.0 검증 기록

검증일: 2026-09-21. 자동화 코딩 도구의 이슈 URL 기반 파일럿을 구현했다.

## 실행한 검증

- 기존 patch/gate 회귀: 24개 통과.
- 새 실행기/게시기 회귀: 20개 통과. 합계 44개.
- `python3 -m sanakan --help`: CLI 진입점 확인.
- `python3 templates/automation/safe_artifacts.py check-schemas`: 통과.
- 검증기에서 파일 링크·Python/JSON/TOML·shell·manifest/checksum 검사.

통합 테스트는 실제 임시 Git 저장소·명령 프로세스·patch 적용·tree 비교를 수행했다.
모델과 GitLab은 모의 어댑터를 사용했다. 별도 테스트에서 가짜 codex 실행 파일을 통해
실제 CLI → subprocess → schema 결과 → ready까지 연결했다. 실제 모델 호출은 아니다.

확인한 실패 경로: 테스트/리뷰/worker 실패 후 수정, 반복 한도, 질문 상태,
승인 밖 파일 변경, 이슈/target 변경, fixture 게시 차단, 조작 patch,
잘못된 reviewer readback, 잠금 충돌, URL allowlist, 만료 설정,
프로세스 timeout, child 환경의 토큰 제외, HTTP redirect 거절,
MR 생성 응답 유실 이후 branch/MR 중복 없는 재시도.
바이너리 신규 파일·삭제·실행 비트 변경의 게시 actions와 최종 tree도 확인했다.

## 검증 경계

- 로컬 Codex CLI 0.139.0의 exec 옵션을 확인했다. 실제 인증 세션/모델 협업은 미실행.
- 실제 GitLab HTTP·권한·MR/reviewer 알림·CI는 미실행.
- Webhook·분산 실행·댓글 답변/리뷰 후 자동 재개·플러그인은 아직 미구현.
- OS/컨테이너·네트워크 격리, 비밀 파일 접근 통제와 운영 비용 제한은 실제 호스트에서 추가 검증해야 한다.
- 이번 구현은 단일 에이전트의 소스 재검토와 자동 테스트로 확인했다.

아래 기록은 이전 가이드 배포 당시의 검증 이력이다.

---

# 1.2.0 검증 기록 (이전 배포 당시 기록)

버전: 1.2.0 · 검증일: 2026-09-21

## 수정 및 검증 범위

- 누락된 Git 설정 및 GitHub/GitLab CI 파일을 복원하고 LICENSE를 배포 목록에 포함했다.
- 수집된 patch와 리뷰 입력을 통일하고, 빈 worker index에서도 독립 checkout에 patch가 적용되는지 검증했다.
- 보호된 필수 검증 정책을 gate의 필수 입력으로 추가했다. 검증 누락, 명령/ID 불일치,
  중복 ID, 빈 정책, baseline 불일치 및 정책 파일 누락을 거절하는 회귀 검증을 수행했다.
- 공통 AGENTS 및 Worker의 승인 조건을 정합화했다. 무인 Low 위험 작업의 별도 제한은 유지한다.

## 검증

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`: 24개 통과.
- `python3 templates/automation/safe_artifacts.py check-schemas`: 통과.
- Ruby Psych: GitHub/GitLab CI YAML 문법 파싱 통과. 플랫폼 서버 lint는 미실행.
- 패키지 무결성 검사: 통과. staged Git tree만 추출한 깨끗한 디렉터리에서도 통과.
- ZIP 생성 및 무결성 검사: 통과. 정확히 50개 manifest 파일 포함, 로컬 상태 파일 제외.
  아래는 재검증 명령이다.

```sh
python3 tools/validate_package.py
python3 tools/build_release.py --output <패키지-밖의-새-ZIP-경로>
```

실제 모델/승인 서비스/Webhook/Runner/Push/MR 생성은 미검증이다.
GitLab CI는 검토된 `GUIDE_VALIDATION_IMAGE` 설정이 필요하다.
이번 수정은 단일 에이전트가 구현 및 diff 재검토했고 독립 에이전트 리뷰는 수행하지 않았다.
아래 독립 검토 설명은 1.1.0 제작 당시 기록이며 이번 수정의 검증 근거가 아니다.

---

# 1.1.0 검증 기록 (이전 배포 당시 기록)

버전: 1.1.0 · 검증일: 2026-09-21

## 범위

이 기록은 가이드 패키지 자체의 정적 검사·오프라인 회귀 테스트에 한정된다.
Studio 애플리케이션의 빌드, 실제 모델 호출, GitLab/GitHub Webhook, 토큰·승인 서버,
Runner 격리, 실제 Push/MR 생성, 운영 DB·배포는 실행하지 않았다.
게시 스크립트는 의도적으로 실패하는 stub이다. 사용 가능한 무인 게시기로 표시하지 않는다.

## 검증 명령 및 결과

| 명령 | 결과 | 비고 |
|---|---|---|
| python3 tools/validate_package.py | 통과 | 링크/JSON/TOML/Python/shell 문법/manifest/checksum |
| PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v | 20개 통과 | 임시 Git fixture만 사용 |
| python3 templates/automation/safe_artifacts.py check-schemas | 통과 | 제공 schema subset의 구조 검사 |
| Ruby Psych YAML parse | 통과 | root GitLab/GitHub 및 consumer CI 예시; 플랫폼 server-side lint 아님 |
| ZIP integrity / manifest comparison | build_release.py의 필수 생성 후 검사 | 불일치 시 성공 보고하지 않음 |

## 독립 검토

스크립트 작성, Studio 적용 문서 작성, 도구 안전성 검토를 분리했다.
독립 검토에서 clean filter 실행 경로와 조작된 manifest 통과를 재현했고 두 항목을 수정했다.
수정 후 필터 marker 미생성·원문 patch 유지 및 manifest 위조 거절을 독립적으로 재확인했다.
이 검토는 완전한 보안 감사나 운영 환경 인증을 의미하지 않는다.

## 운영 확대 전 남은 검증

- 배포한 Codex 버전·모델·계정·프로젝트 신뢰 설정에 대한 실제 실행.
- 플랫폼 CI lint, 고정된 Runner image/action의 조직 승인.
- 승인자·서명·중복 이벤트·상태 저장소·동시성·부분 성공 후 재시도.
- 보호된 게시기의 별도 코드·권한·토큰 격리 및 최종 commit digest 일치.
- 소비자 프로젝트의 실제 build·test·DB migration.
- 공개 배포 권리 및 라이선스 확정.

## Context Usage Report

### Investigation Summary

| Item | Result |
|---|---|
| Task type | 검토 완료 가이드의 최종 배포 패키지 제작 |
| Main target | 정책·검증 도구·자동화 경계·게시 문서 |
| Strategy | 원본 목록/검토 결과 → 소유 범위별 보완 → 독립 검토 → 오프라인 검증 |
| Verification boundary | 실제 서비스/모델/게시 권한은 미검증 |

### Search And CodeGraph Usage

| Category | Details |
|---|---|
| Search terms | verify, patch, publish, schema, baseline, sandbox |
| CodeGraph | 문서/스크립트 배포 작업이므로 미사용 |
| Candidates | 원본 ZIP 29개 항목과 추가 도구/문서 |
| Selected | 위험 경계가 있는 CI·publisher·verify·schema 및 정책 서식 |

### File Inspection Scope

| File/Area | Read Scope | Reason |
|---|---|---|
| 원본 README | Partial | 기존 검토와 목차를 토대로 재구성 |
| 정책/agent/checklist 서식 | Full | 실제 프로젝트 목적 및 역할 일치 |
| safe_artifacts/verify/tests | Full | 구현자·독립 리뷰어가 동작 검토 |
| Studio 코드/설정 | Partial | 문서의 stack/명령 대조만 수행 |
| 공식 Codex 문서 | Partial | 설정과 권한 전제 확인 |

### Evidence Checked

| Type | Item | Result |
|---|---|---|
| Source | 사용자 제공 원문과 검토 결과 | 반영 |
| Tests | 오프라인 fixture | 위 검증 표 참고 |
| Output | manifest/sha256/ZIP | 위 검증 표 참고 |

### Files Or Areas Intentionally Not Read

| Area | Reason | Risk |
|---|---|---|
| 실제 credential·환경값 | 배포물에 불필요, 노출 방지 | Low |
| 전체 RAG 앱 구현 | 가이드 적용과 무관 | Low |
| 운영 CI/권한 설정 | 대상 설치 환경 미확정 | Medium |

### Original Source Verification

| Item | Method | Result |
|---|---|---|
| 원문/패키지 | 직접 읽기와 독립 리뷰 | 수행 |
| 실제 모델/DB/게시 | 실행하지 않음 | Not verified |
| 로컬 검사 | 실행 명령 기록 | 위 표 참고 |

### Context Efficiency Metrics

| Metric | Count |
|---|---:|
| 원본 ZIP 엔트리 | 29 |
| 위임된 범위 | 3 |
| 실제 원격 게시 | 0 |
| 기존 프로젝트 코드 변경 | 0 |

### Final Assessment

| Rule | Result | Comment |
|---|---|---|
| Search before reading | Pass | 원본 목록과 이전 검토 재사용 |
| Narrow candidates | Pass | 정책/도구/문서 소유 범위 분리 |
| Avoid large reads | Partial | 공식 문서 navigation 일부 포함 |
| Skipped areas recorded | Pass | 운영 권한/credential 제외 |
| Verify original/output | Pass | 검사와 독립 검토 |

Conclusion: Context usage was partially controlled. Some files, logs, or diffs may have been read more broadly than necessary.
