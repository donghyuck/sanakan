# Sanakan — Codex 에이전트 협업 자동화 코딩 도구

**개발 버전 1.3.0 · 2026-09-21**

Sanakan은 GitLab 이슈를 받아 Codex 에이전트가 계획·개발·검증·독립 리뷰를 수행하고,
Draft MR을 생성해 사람에게 리뷰를 요청하는 도구를 개발하는 프로젝트입니다.
기존 개발 운영 가이드와 템플릿은 이 도구의 정책·설정 기반으로 유지합니다.

## 현재 실행 가능한 범위

이슈 URL을 시작점으로 하는 **단일 호스트 파일럿 실행기**를 제공합니다.

```text
이슈 URL → 메인 에이전트 계획 → 개발 에이전트 구현 → 필수 검증
                                      ↑                ↓
                                      └─ 수정 피드백 ← 독립 리뷰
                                                       ↓
                                                     ready
                                                       ↓ 별도 게시 환경
                                            Draft MR → 사람 리뷰 요청
```

- `python3 -m sanakan run`: 이슈 수신, 격리 clone, 독립 Codex 세션, 검증·리뷰·수정 반복.
- `python3 -m sanakan publish`: 동일 issue/baseline/patch를 재확인하고 GitLab branch·commit·Draft MR 및 reviewer 설정.
- 메인/개발/리뷰는 별도 `codex exec` 세션이며 Python 조정기가 결과 전달과 역할 실행을 관리합니다.
- 필수 검증과 게시 조건은 프로그램이 검사합니다. 모델의 성공 주장만으로 게시하지 않습니다.
- 개발/검증 과정에 게시 토큰을 제공하지 않습니다. 게시기는 생성된 프로젝트 코드를 실행하지 않습니다.

실제 Codex/GitLab 연동 실증은 아직 수행하지 않았습니다. Webhook 서버, 분산 큐, 댓글 답변 후 자동 재개,
사람 리뷰 피드백 수신, 플러그인 설치, 자동 병합·배포는 후속 단계입니다.
**이슈 등록 이벤트에 바로 연결되는 완성된 운영 서비스로 배포하지 마세요.**

## 시작하기

먼저 [실행 명세](docs/EXECUTION_SPEC.md)와 [실행기 사용법](docs/RUNNER.md)을 읽고
[프로젝트 설정 예시](examples/runner/project.json)의 대상·기준 commit·허용 경로·검증·리뷰어를 정합니다.
기존 프로젝트의 AGENTS를 읽고 따르며 가이드 전체를 덮어쓰지 않습니다.

```sh
python3 -m sanakan --help
python3 -m sanakan run \
  --config /protected/project.json \
  --issue https://gitlab.example.com/team/project/-/issues/123 \
  --runs /var/lib/sanakan/runs
```

실행에는 POSIX, Python 3.11+, Git, 인증된 Codex CLI와 개발 전용 환경이 필요합니다.
읽기 토큰·게시 토큰의 분리 및 게시 명령은 사용법에 설명합니다.
별도 clone과 환경변수 필터링만으로 OS/네트워크 격리가 보장되지는 않습니다.

## 로컬 검증

아래 검증은 모델·원격 API·토큰 없이 임시 Git 저장소에서 실행됩니다.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 tools/validate_package.py
```

실제 테스트 프로세스와 Git 변경을 사용하며 Codex/GitLab 응답은 모의 처리합니다.
통과가 실제 모델 품질, GitLab 권한 또는 운영 환경 격리 검증을 의미하지는 않습니다.

## 저장소 구성

| 경로 | 역할 |
|---|---|
| `sanakan/` | 실행 조정, Codex 어댑터, GitLab API, 별도 게시기 |
| `tests/` | 패치/gate 및 실행기·게시기 오프라인 회귀 검증 |
| `templates/automation/` | 보호된 patch 수집·gate·schema·프롬프트 |
| `templates/` | 소비자 프로젝트에 선택 적용하는 운영 정책 |
| `docs/` | 실행 명세, 사용법, 프로젝트 도입 안내 |
| `tools/` | 패키지 검증 및 ZIP 생성 |

`templates/automation/publish-branch-and-mr.sh`는 이전 참조 템플릿의 차단 stub으로 남아 있습니다.
새 게시 구현은 `sanakan/publisher.py`이며 동일 기능으로 혼동하지 마세요.

## 가이드와 배포

- [신규 프로젝트](01_NEW_PROJECT_CHECKLIST.md) / [기존 프로젝트](02_EXISTING_PROJECT_CHECKLIST.md)
- [보안 체크리스트](03_SECURITY_CHECKLIST.md) / [단계별 도입](docs/ROLLOUT_CHECKLIST.md)
- [Studio 적용 안내](docs/STUDIO_ADOPTION.md) — 이전 조사 기반이며 실제 적용 시 재확인
- [참조 검증 도구](templates/automation/README.md)
- [검증 기록](VALIDATION.md) / [변경 이력](CHANGELOG.md) / [게시 안내](PUBLISHING.md)

소스와 배포 파일의 일치는 MANIFEST/SHA256SUMS로 검사합니다. 코드 변경 후 검토·테스트를 수행하고
`python3 tools/validate_package.py --refresh`로 목록을 갱신합니다.
플러그인은 이 실행 흐름이 실증된 후 설치·설정·점검 수단으로 추가할 예정입니다.
