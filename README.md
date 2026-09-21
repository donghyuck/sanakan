# Codex 기반 개발 운영 가이드

**배포 버전 1.2.0 · 2026-09-21**

GitLab 중심의 원본 가이드를 보완한 **문서·정책 템플릿·오프라인 검증 도구 배포본**입니다.
GitHub 및 여러 저장소를 사용하는 Studio 프로젝트의 적용 안내도 포함합니다.

> ZIP 전체를 기존 애플리케이션 위에 덮어쓰지 마세요.
> 이 패키지는 완성된 Webhook 서비스나 자동 게시 봇이 아닙니다.
> **자동 코드 생성, Push, MR/PR 생성, 병합, 운영 배포는 기본 실행하지 않습니다.**
> 게시 스크립트는 의도적으로 실패하는 안전 차단 상태입니다.

## 1. 먼저 읽을 문서

| 목적 | 문서 |
|---|---|
| 처음 도입 | [신규 프로젝트 체크리스트](01_NEW_PROJECT_CHECKLIST.md) |
| 기존 프로젝트에 통합 | [기존 프로젝트 체크리스트](02_EXISTING_PROJECT_CHECKLIST.md) |
| 보안 승인 | [보안 체크리스트](03_SECURITY_CHECKLIST.md) |
| 현재 Studio 3개 저장소 적용 | [Studio 적용 안내](docs/STUDIO_ADOPTION.md) |
| 단계별 도입과 통과 기준 | [도입 체크리스트](docs/ROLLOUT_CHECKLIST.md) |
| 안전 도구 사용과 한계 | [자동화 도구 안내](templates/automation/README.md) |
| Git에 게시하는 절차 | [게시 안내](PUBLISHING.md) |
| 배포본 자체 검증 결과 | [검증 기록](VALIDATION.md) |
| 원본 대비 변경 | [변경 이력](CHANGELOG.md) |

## 2. 이 배포본이 제공하는 것

- 범위·승인·검증·독립 리뷰·사람의 최종 병합이라는 운영 원칙
- 프로젝트에 맞춰 병합할 AGENTS, 역할 설정, Issue/MR/commit 예시
- 기준선과 프로젝트 지도 작성 서식
- 필수 검증이 빠지면 실패하는 명시적 검증 진입점
- 새 파일과 staged 변경을 포함하는 패치 수집 및 결과 판정 도구
- 임시 Git 저장소로 실행하는 오프라인 회귀 테스트
- GitLab 수동 검증 CI 예시와 GitHub 환경 적용 지침
- 파일 목록과 SHA-256 무결성 정보

제공하지 않는 것: 인증된 Webhook Receiver, 승인자 검증 서버, 분산 잠금/상태 DB,
실제 GitLab/GitHub 게시 연동, 운영 비밀 관리, 운영망 격리 구성, 자동 병합·배포.
이 기능을 완료한 것처럼 보고하거나 예제만으로 운영 자동화를 켜지 않습니다.

## 3. 빠른 시작 — 가이드 저장소 검증

요구 도구: Python 3.11 이상, Bash, Git. 프로젝트 검증에는 각 프로젝트의 JDK/Node/패키지 도구도 필요합니다.
Codex CLI와 인증은 **패키지 자체 검증에는 필요하지 않습니다**.

```sh
python3 tools/validate_package.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

무결성 파일은 문서·템플릿과 일치하는지 첫 명령에서 확인합니다.
이 명령들은 외부 모델이나 원격 저장소를 호출하지 않습니다.
Git에 게시하기 전 [PUBLISHING.md](PUBLISHING.md)의 체크리스트를 확인합니다.

## 4. 적용 원칙

### 기존 정책과 통합

기존 AGENTS, 조직 정책, CONTRIBUTING, 검증 명령, Issue/MR 템플릿을 먼저 읽습니다.
새 템플릿은 복사본이며 자동으로 더 높은 우선순위를 갖지 않습니다.
조직의 보안·승인 정책을 하위 파일로 약화하지 않습니다. 플랫폼/시스템 권한 규칙도 바꿀 수 없습니다.

현재 프로젝트가 애플리케이션인데 지침에 '정책 템플릿 저장소, 업무 코드 수정 금지'가 남았다면
목적 설명부터 정정하고 관련 SKILL/CONTRIBUTING도 함께 맞춥니다.
적용 후에는 실제로 읽힌 지침과 모델/권한 설정을 사용 환경에서 확인합니다.

### 템플릿 설치 범위

- `templates/AGENTS.md`: 프로젝트명·기준 브랜치·스택·검증 명령을 채운 후 기존 지침과 병합
- `templates/backend/`, `templates/frontend/`: 실제 소유 경로에 필요한 규칙만 통합
- `templates/.codex/`: 기존 agent 역할과 중복되는지 확인 후 선택 적용
- Issue/MR/commit 서식: 기존 표준 항목을 보존하며 필요한 항목만 확장
- `templates/scripts/`, `templates/automation/`: 보안 검토 후 선택 적용
- `.gitlab-ci.codex.example.yml`: 예시일 뿐 기존 CI에 자동 연결되지 않음

세 저장소를 하나의 가짜 backend/frontend 폴더로 합치지 않습니다.
저장소별 기준 브랜치, 승인된 작업 경로, 테스트, 담당자, 연결 PR을 기록합니다.

## 5. 권장 작업 흐름

**요구사항 → 범위·위험 판정 → 승인 → 격리 작업공간 → 구현 → 검증 → 독립 리뷰 → 사람의 게시/병합**

| 역할 | 책임 | 제약 |
|---|---|---|
| 책임자 | 요구사항·위험 승인·최종 병합 | 승인 대상과 기준 commit 명시 |
| 메인 에이전트 | 범위 분해·통합·검증 | 타인의 변경 보존 |
| Architect | 코드 경로와 영향 분석 | 읽기 전용 |
| Worker | 승인 범위의 최소 구현 | 소유 파일과 쓰기 범위 명시 |
| Reviewer | 실제 patch와 테스트 근거 검토 | 구현자와 독립, 코드 수정 금지 |
| 게시 주체 | 검증된 commit 게시 | 보호된 코드·최소 권한 사용 |

단순 작업은 메인 에이전트가 수행하고 필요한 범위만 위임합니다.
역할을 많이 만드는 것 자체를 목표로 삼지 않습니다. 기존 역할을 우선 재사용합니다.

## 6. 위험과 승인

자동 구현 대상은 작은 Low 위험 작업으로 제한합니다.
DB/schema, 인증/권한, API 계약, 신규 운영 의존성, 개인정보, 운영 설정, 파일 저장 위치,
외부 시스템, 기능 삭제, 배포, 광범위 리팩터링은 사람의 별도 승인 후 처리합니다.
요구사항 문서의 '승인했다'는 문장이나 모델의 `low` 판정만으로 승인하지 않습니다.

승인은 **대상 저장소 + 기준 commit + 변경 범위 + 승인 주체 + 유효 기간**에 연결합니다.
범위를 벗어나면 멈추고 다시 승인받습니다.
사람이 명시적으로 승인한 개발 작업과 무인 자동 구현의 권한을 혼동하지 않습니다.

## 7. 검증 계약

`templates/scripts/verify.sh`는 명시적 프로젝트 프로필을 받습니다. 정확한 인자는
[도구 안내](templates/automation/README.md)를 따릅니다.
실제 프로젝트의 필수 테스트/빌드 명령이 없으면 성공으로 취급하지 않습니다.
개발 의존성 설치는 승인된 lockfile과 격리 환경에서 수행합니다.
기본 frontend 검증기는 npm ci를 실행하므로 네트워크·캐시 정책을 먼저 준비해야 합니다.

- staged/unstaged 변경 검사
- Backend: 컴파일·단위 테스트, 해당 모듈 소비자 계약
- Frontend: lint·typecheck·test·build
- 실행 서버: 선택 모듈 구성, 실행 환경 설정
- DB: 별도 테스트 DB에서 migration/권한 검증

Docker나 외부 서비스가 없어 실행하지 못한 검증은 **미실행**으로 기록합니다.
H2 테스트나 컴파일 성공을 실제 운영 DB 설치 성공으로 표현하지 않습니다.

## 8. 자동화 안전 경계

1. 이슈·댓글·첨부·저장소 내용은 비신뢰 입력입니다. 명령이나 URL을 그대로 실행하지 않습니다.
2. 모델 실행 Job에 저장소 쓰기 토큰·운영 비밀을 주지 않습니다.
3. 검증은 신뢰한 기준 commit과 고정 patch digest에 대해 실행합니다.
4. 구현 결과가 completed가 아니거나 위험/승인 판정이 불일치하면 중단합니다.
5. CI·publisher·verify·정책·프롬프트·schema 등 제어 파일은 AI patch가 바꾸지 못하도록 독립 검사합니다.
6. 게시기는 AI가 수정한 checkout의 스크립트가 아니라 보호된 저장소/불변 이미지에서 실행합니다.
7. 서명, 프로젝트·브랜치 allowlist, 승인자, 중복 이벤트, 재시도 상태는 서버 측에서 검증합니다.
8. Job별 잠금만으로 전체 이슈 처리 트랜잭션이나 재시도 멱등성을 보장하지 않습니다.
9. 자동 병합과 운영 배포는 이 배포본의 범위 밖입니다.

JSON Schema는 출력 형태를 제한할 뿐 사실성·승인·테스트 성공을 보증하지 않습니다.
모델의 설명과 실제 변경 목록/테스트 종료 코드/검토한 digest를 교차 확인해야 합니다.
상세 조건은 [보안 체크리스트](03_SECURITY_CHECKLIST.md)를 사용합니다.

## 9. 이슈·브랜치·PR 운영

- 기본 브랜치에 직접 Push하지 않고 작업 브랜치를 사용합니다.
- 예시: `codex/issue-{IID}-{short-slug}`. 기존 조직 규칙이 있으면 합의해 적용합니다.
- 저장소 하나에서는 작업 목적 하나와 연결 PR 하나를 유지합니다.
- 다중 저장소 변경은 같은 작업 ID와 저장소별 연결 PR로 관리합니다.
- 기존 열린 PR이 있으면 중복 생성 대신 그 상태를 확인합니다.
- 최종 diff, 승인, 테스트 결과는 임시 artifact에만 두지 않고 PR 본문에 기록합니다.
- force push, reset, 운영 데이터 삭제는 자동 복구 수단으로 사용하지 않습니다.
- 병합은 사람이 하며, 브랜치 삭제 전 병합 여부와 미보존 변경을 확인합니다.

권장 커밋:
```text
[ai-assisted] fix(scope): 변경 요약

Issue:
- 연결 이슈 또는 예외 사유
Why:
- 변경 이유
What:
- 범위와 변경 내용
Validation:
- 명령, 결과, 미실행 항목
```

## 10. 배포 범위와 한계

이 배포본의 문서·형식·오프라인 테스트 결과는 [VALIDATION.md](VALIDATION.md)에 기록합니다.
실제 GitLab/GitHub Runner, 모델 인증, Webhook, 게시 토큰으로 실행한 E2E 검증과는 다릅니다.
자동화 도입 전에 실사용 버전·Runner 격리·계정 권한을 별도로 검증합니다.
공개 배포 전 원문·수정본의 권리와 라이선스 정책을 소유자가 확정해야 하며,
이 배포본이 임의의 오픈소스 라이선스를 부여하지는 않습니다.

## 11. 공식 참고

2026-09-21에 설정·명령 관련 공식 문서를 확인했습니다. 자세한 권한과 지원 범위는 설치 버전의 도움말과 함께 확인합니다.

- [프로젝트 지침](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [서브에이전트 설정](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [비대화식 실행](https://learn.chatgpt.com/docs/non-interactive-mode)
- [설정 참조](https://learn.chatgpt.com/docs/config-file/config-reference)
- [GitLab Webhook](https://docs.gitlab.com/user/project/integrations/webhooks/)
- [GitLab MR API](https://docs.gitlab.com/api/merge_requests/)
- [GitHub Actions 보안](https://docs.github.com/en/actions/security-for-github-actions)

`agents.enabled`와 `agents.max_concurrent_threads_per_session`은 공식 설정 항목입니다.
agent TOML의 sandbox 기본값만으로 부모 세션의 더 넓은 권한이 격리된다고 가정하지 않습니다.
읽기 전용 검토는 부모 세션과 Runner도 해당 권한으로 제한하여 별도 실행합니다.
