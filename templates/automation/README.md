# 오프라인 자동화 참조 도구

이 문서는 기존 참조 템플릿에 관한 설명입니다. 새 파일럿 실행기와 별도 게시기는
[Sanakan 사용법](../../docs/RUNNER.md)을 따릅니다.

이 폴더는 **운영 자동화 서비스가 아닌 1.2.0 참조 구현**입니다.
완성된 Webhook Receiver, 모델 실행기, 승인 서비스, 게시 서비스는 제공하지 않습니다.
`publish-branch-and-mr.sh`는 항상 종료 코드 2로 실패하며 네트워크/토큰을 사용하지 않습니다.

## 신뢰 경계

- Python 3.11+, Git, Bash가 필요합니다. 외부 Python 패키지는 필요하지 않습니다.
- 도구·schema·allowlist·필수 검증 정책·기준 commit은 **worker가 바꿀 수 없는 보호 위치**에서 제공합니다.
- worker가 종료된 독립 작업공간에서 수집합니다. 실행 중 동시 변경/악성 파일시스템에 대한 sandbox가 아닙니다.
- 승인된 저장소와 전체 commit ID를 작업 시작 전에 기록합니다. 작업 후 HEAD를 기준선으로 새로 정하지 않습니다.
- allowlist는 사람이 승인한 **정확한 상대 파일 경로의 JSON 배열**입니다. 예: `["src/example.py", "tests/test_example.py"]`. 디렉터리/glob 패턴은 지원하지 않습니다.
- 정책·CI·스크립트·프롬프트·schema·빌드 제어 파일, symlink, submodule 변경은 이 낮은 위험도 경로에서 거절합니다. 별도 사람 검토 경로로 처리합니다.
- CODEOWNERS도 보호 대상입니다. submodule을 포함한 저장소는 이 수집기가 지원하지 않습니다.
- 이 allowlist는 내용 기반 보안 검사나 비밀 탐지기가 아닙니다. 인증/DB/운영 영향은 독립 리뷰로 확인합니다.

## 1. Schema 자체 확인

가이드 저장소에서는:

```sh
python3 templates/automation/safe_artifacts.py check-schemas
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_automation.py -v
```

소비자 프로젝트에 `templates/automation/`을 `automation/`으로 설치했다면 경로만 바꿉니다.
테스트는 가이드 저장소의 임시 Git fixture에서 수행되므로 소비자 프로젝트에 `tests/`를 덮어쓰지 않습니다.

## 2. 고정 기준선의 patch 수집

```sh
python3 /protected/automation/safe_artifacts.py collect \
  --repo /isolated/project \
  --baseline APPROVED_FULL_COMMIT_SHA \
  --allowlist /protected/approved-paths.json \
  --output-prefix /artifacts/change-001
```

출력은 `change-001.patch`와 `change-001.json`입니다. 출력 디렉터리는 미리 만들고,
기존 파일을 덮어쓰지 않도록 실행마다 새 prefix를 사용합니다.

수집은 기준 commit 대비 **최종 작업 트리 상태**를 대상으로 하며 staged/unstaged 수정,
신규 파일, 삭제, 바이너리를 포함합니다. index에만 존재하고 작업 트리에서는 다시 지워진 파일은
최종 결과에 넣지 않습니다. ignored 신규 파일과 `.agent/` 결과물은 제외합니다.
원 index·작업 트리는 건드리지 않지만 Git object database에 수집용 blob/tree 객체는 기록합니다.
원 index 대신 임시 index를 사용하며 clean filter/textconv/external diff는 실행하지 않습니다.
수집은 raw bytes 비교이므로 clean/smudge 필터나 CRLF 정규화 결과를 재현하지 않습니다.
LFS·필터가 필요한 저장소 또는 줄바꿈 변환 환경은 별도 승인된 수집기로 검증하고 이 참조 구현을 그대로 사용하지 않습니다.
작업 트리의 git diff 대신 파일 목록과 raw blob hash를 비교합니다. Git 환경 override는 제거하고
literal pathspec, hooks 비활성화, fsmonitor 비활성화를 적용합니다. 이미 악성 코드가 실행 중인
작업공간이나 임의 Git 설치/전역 설정의 모든 공격면을 격리하는 도구는 아닙니다.
HEAD가 달라졌거나 승인 범위 밖 파일이 변경되면 중단합니다. HEAD 이동을 승인으로 간주하지 않습니다.

## 3. 독립 검증과 리뷰

보호된 orchestrator가 승인 baseline의 깨끗한 별도 checkout에 `git apply --index /artifacts/change-001.patch`로 고정 patch를 적용합니다.
적용 실패 시 중단합니다. verifier는 이 checkout에서 필수 검증을 실행합니다.
Reviewer는 불변 patch 파일의 SHA-256을 직접 확인하고 이 checkout에서 호출 흐름을 읽습니다.
worker의 index는 수집기가 변경하지 않으므로 worker의 staged diff를 리뷰 대상으로 사용하지 않습니다.
검증 job은 프로젝트 코드를 실행하므로 게시 토큰·운영 비밀을 주지 않습니다.
검증/리뷰를 실행한 정확한 patch SHA-256과 baseline을 각 결과에 기록합니다.

- `triage.json`: 승인된 기준 commit, 예상 파일, low 위험 판정, 정보/승인 누락 없음
- `implementation.json`: completed, 실제 파일 목록, 검증 결과, 완료 조건별 `acceptance_results`, 미확인/질문/위험 없음
- `review.json`: 독립 리뷰의 pass, blocking_count 0, blocking/high finding 없음
- `verification-policy.json`: 보호된 기준 commit과 필수 검증 ID/정확한 명령 목록
- `verification.json`: 신뢰한 runner가 작성한 passed와 실제 check_ids/명령/종료 코드(모두 0)
- 각 파일은 `schemas/`의 필수 필드 및 추가 필드 금지 규칙을 따릅니다.

작업 시작 전에 사람이 승인한 `verification-policy.json`을 worker가 수정할 수 없는 위치에 고정합니다.
`triage.test_plan`은 제안이며 이 정책을 대체하지 않습니다. runner는 정책의 각 명령을 실행하고
동일 순서의 `check_ids`, `commands`, `exit_codes`를 기록합니다. 누락·중복·알 수 없는 ID나
명령 불일치는 실패합니다. 추가 검증도 먼저 정책에 포함해야 합니다.

```json
{
  "baseline": "0000000000000000000000000000000000000000",
  "checks": [{"id": "backend", "command": "bash scripts/verify.sh backend"}]
}
```

`verification.json` 예시 형식(해시/명령은 실제 실행값으로 대체):

```json
{
  "baseline": "0000000000000000000000000000000000000000",
  "patch_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "status": "passed",
  "check_ids": ["backend"],
  "commands": ["bash scripts/verify.sh backend"],
  "exit_codes": [0]
}
```

모델이 verification 파일을 작성하거나 로그를 요약한 것을 독립 실행 증거로 인정하지 않습니다.
JSON Schema 및 digest는 형식/일치 여부를 검사할 뿐 승인자·서명·테스트 사실성을 증명하지 않습니다.
trusted collector manifest는 artifact 저장소에 고정해야 합니다.
gate는 임시 디렉터리의 Git patch parser로 실제 변경 경로를 읽고 manifest와 완전히 일치하는지
확인합니다. rename/copy 표현은 거절하며 delete/add 표현만 허용합니다. symlink/submodule mode도
거절합니다. 이 검사는 출처가 불명인 artifact를 신뢰할 근거가 되지 않습니다.

## 4. 보수적 상태 gate

```sh
python3 /protected/automation/safe_artifacts.py gate \
  --baseline APPROVED_FULL_COMMIT_SHA \
  --allowlist /protected/approved-paths.json \
  --manifest /artifacts/change-001.json \
  --patch /artifacts/change-001.patch \
  --triage /artifacts/triage.json \
  --implementation /artifacts/implementation.json \
  --review /artifacts/review.json \
  --verification /artifacts/verification.json \
  --verification-policy /protected/verification-policy.json
```

blocked/failed/no_change, schema 누락/오류, 범위 불일치, 미충족 완료 조건, 검증 실패,
미해결 질문/위험, hash 또는 baseline 불일치는 실패합니다.
성공은 **사람의 승인이나 게시 허가가 아닙니다**. medium/high 위험 작업은 별도 승인 워크플로로 보냅니다.
script/schema 자체가 바뀌거나 서명·보관 권한을 신뢰할 수 없다면 gate 결과도 신뢰할 수 없습니다.

## 5. 소비자 프로젝트 검증 스크립트

`templates/scripts/verify.sh`를 검토해 `scripts/verify.sh`에 설치합니다.
모든 명령은 소비자 프로젝트 루트를 기준으로 합니다.

```sh
bash scripts/verify.sh backend
bash scripts/verify.sh frontend
bash scripts/verify.sh combined backend frontend
```

인자 순서는 `프로필 [backend-dir] [frontend-dir]`입니다.
예를 들어 frontend만 하위 폴더에 있으면 `frontend . frontend`를 사용합니다.

- Backend: Gradle wrapper의 `test build` 또는 Maven wrapper의 `verify`가 필수입니다.
- Frontend: package.json/package-lock.json, `lint`·`typecheck`·`test:ci`·`build`가 모두 필수입니다.
  `test:ci`는 watcher가 아닌 종료형 명령으로 정의합니다. 스크립트가 `npm ci` 후 순서대로 실행합니다.
- wrapper/lockfile/명령 누락은 실패입니다. `--if-present`로 검증을 건너뛰지 않습니다.
- 의존성 설치/빌드는 저장소 코드를 실행할 수 있습니다. 승인된 lockfile, 격리 환경, 제한된 네트워크 정책을 사용합니다.
- monorepo/모듈 소비자/DB/성능 검증은 이 공통 스크립트만으로 완료되지 않습니다.
  필수 검증을 보호된 프로젝트별 wrapper에 추가하고 미실행은 기록합니다.
- root README의 패키지 검증과 소비자 애플리케이션 검증은 별개입니다.

## 6. CI 및 실제 게시 도입

`templates/.gitlab-ci.codex.example.yml`은 소비자 프로젝트용 **수동 opt-in syntax/schema 확인 예시**입니다.
`automation/` 설치 후 `ENABLE_CODEX_REFERENCE_CHECK=true`로 web pipeline을 열고 job도 수동 실행합니다.
`CODEX_REFERENCE_IMAGE`는 Python/Git/Bash가 있는 검토·고정된 이미지로 설정합니다.
이 job은 모델/외부 API/게시를 실행하지 않으며 사용자 애플리케이션 테스트도 대신하지 않습니다.
가이드 저장소 자체 CI와 혼동하지 마세요.

실제 게시 연동은 별도 보호된 코드/불변 이미지에서 구현하고 다음을 확인해야 합니다.

1. Webhook 서명·프로젝트/브랜치 allowlist·승인자의 권한·만료 검증
2. 이슈별 전체 상태 전이와 멱등성·동시 실행·재시도 잠금
3. 기준 commit 및 patch digest에 연결된 변경 불가능한 검증·리뷰 증거
4. worker·검증 job과 격리된 최소 권한 게시 토큰
5. 승인된 템플릿의 한국어 커밋/PR 본문과 검증 결과·미실행 항목·이슈 예외 기록
6. PR 중복 방지와 게시 결과 readback, 사람의 최종 병합

실운영 인증, webhook, runner, push/MR API의 E2E는 이 배포본에서 검증하지 않았습니다.
