# studio-api 적용 검토와 첫 실증 절차

**현재 상태: 지침 정정과 로컬 실증을 완료하고 검증된 테스트 변경을 원본 작업트리에 반영했다.**
검토일은 2026-09-22이다. 실제 적용 전에 아래 commit과 환경이 여전히 같은지 확인한다.
이 문서는 사전 검토와 후속 로컬 적용을 구분해 기록한다. 원격 게시와 운영 자동화는 활성화하지 않았다.

## 후속 적용 결과

- studio-api의 AGENTS/AI_DEVELOPMENT_POLICY/CONTRIBUTING/SKILL 목적 지침을 애플리케이션 개발 기준으로 정정했다.
- 기존 branch/commit/Issue/PR/사람 리뷰 규칙을 유지하고 POLICY_VERSION v1.7.0 및 사용 안내를 반영했다.
- 원본 HEAD를 바꾸지 않고 지침을 포함한 별도 snapshot에서 실제 Codex를 실행했다.
- 테스트 파일 하나에 code point/keyword 경계값 테스트 3개를 추가했다. 업무 코드는 바꾸지 않았다.
- 독립 호스트 검증 10개 통과, 읽기 전용 완료 보고 completed, 독립 리뷰 pass(차단 0건), 최종 ready.
- 고정 patch와 원본 반영 파일의 bytes가 일치함을 확인했다. 원본 index/HEAD와 기존 .omx 변경은 보존했다.
- 실제 설정은 저장소 밖의 ~/.config/sanakan/studio-api에 배치했다. 반복 사용용 project.json은 지침 commit 후 새 baseline으로 활성화한다.

실증 중 선택 문서 부재의 잘못된 차단, 600초 시간 제한, Worker sandbox의 Gradle lock/socket 제한을 만났다.
선택 문서와 호스트 입력의 우선순위를 정정하고, 시간 제한을 1200초로 조정했다.
검증은 sandbox를 해제하는 대신 Worker의 implemented 인계 → 호스트 검증 → 읽기 전용 완료 보고로 연결했다.
초기 중단/실패 기록도 보존했다. 아래는 적용 전 조사 기록이며 이후 상태와 구분한다.

## 직접 확인한 상태

| 항목 | 확인 결과 |
|---|---|
| 원격 | GitHub `donghyuck/studio-api` |
| GitHub repository ID | `1013485836` — API 읽기로 확인 |
| 원격 기본 브랜치 | `main` |
| 이번 실증의 기준 브랜치 | `3.x` — 기본 브랜치와 구분 |
| 로컬 HEAD / 원격 3.x | 모두 `c8457b601303338492431a3c60748d7a9e3996bd` |
| 스택 | Java toolchain/release 17, Spring Boot 4.1.0, Gradle wrapper 8.14.5 |
| 작업 머신 Java | Corretto 17.0.8 |
| 미커밋 변경 | `.omx/` 상태 파일 4개. 이번 작업에서 보존 |
| Docker | 데몬 연결 불가. 컨테이너 실증 미수행 |

버전은 build.gradle.kts의 기본값만 보지 않고 gradle.properties의 실제 override를 함께 확인했다.
설정 파일 전체나 credential 값은 가이드에 복사하지 않는다.

## 1. 먼저 프로젝트 지침을 바로잡는다

현재 애플리케이션 저장소에 정책 템플릿 유지보수용 지침이 남아 있다.

| 파일 | 충돌 내용 | 정리 방향 |
|---|---|---|
| AGENTS.md | policy-first repository라고 설명 | 모듈형 Studio API 애플리케이션 개발 저장소임을 명시 |
| CONTRIBUTING.md | 애플리케이션 코드/업무 기능 추가 금지 | 실제 프로젝트의 개발·검증 절차로 정정 |
| SKILL.md | template maintainer, 제품 동작 추가 금지 | Studio API의 개발 수명주기로 정정 |
| AI_DEVELOPMENT_POLICY.md | SKILL/문서 소유권을 템플릿 정비용으로 설명 | 위 세 파일과 용어·적용 범위를 일치시킴 |

기존 SPEC → BUILD → REVIEW → SECURITY → DOCS, 사람 최종 리뷰, 비밀 보호,
검증 기록, commit/Issue/PR 필수 항목은 유지한다. 새 AGENTS로 통째로 덮어쓰지 않는다.
GitLab 템플릿 참조는 GitHub PR에서도 같은 필수 항목을 사용하도록 연결한다.
정책·절차를 변경하면 대상 프로젝트의 CHANGELOG/POLICY_VERSION 규칙도 함께 확인한다.

이 정리는 별도 정책 변경으로 먼저 검토해야 한다. 이번 적용 검토에서는 대상 파일을 수정하지 않았다.
Sanakan의 Low 위험 경로는 AGENTS/정책 파일 수정을 차단하므로 자동 코딩 작업에 정책 정리를 섞지 않는다.

## 2. 작은 기준 테스트를 별도 작업공간에서 실행한다

Sanakan의 checkout 함수로 원본 HEAD를 별도 저장소에 가져왔다. 원본의 미커밋 변경은 포함하지 않았다.
선택한 대상은 DB/서버 없이 동작하는 `studio-platform-document-metadata`의 단위 테스트다.

```sh
bash ./gradlew --offline --no-daemon --console=plain --max-workers=1 \
  :studio-platform-document-metadata:test \
  --tests '*BuiltInDocumentMetadataSchemaRegistryTest'
```

**실행 결과: 성공. 테스트 7개, 실패 0, 오류 0, skip 0.**
JUnit XML을 확인했으며 전체 애플리케이션 테스트 통과로 확대 해석하지 않는다.
별도 작업공간에서도 tracked 변경이 없었고, 원본에는 기존 .omx 변경 4개만 남았다.
원본 코드·서버·DB·공유 JAR·Git 원격을 변경하지 않았다.

이 결과는 현재 머신의 Gradle 캐시를 사용한 offline 검증이다. 빈 캐시나 Docker 이미지에서도
성공한다는 의미는 아니다. `--offline`을 제거해 실패를 감추기 전에 의존성 준비 절차를 정한다.

## 3. 첫 자동 개발 후보와 설정

추천 후보는 **DocumentMetadataProjectionPolicy의 경계값 단위 테스트 보강**이다.
현재 코드에 summary 480 code points, keyword 80 code points 및 최대 8개 제한이 있으므로
빈 값·중복·보조 평면 문자·개수 제한 등을 테스트할 수 있다. 새 결함을 발견했다고 주장하는 것은 아니다.

첫 작업은 기존 테스트 파일 하나만 수정하도록 한다.

```text
studio-platform-document-metadata/src/test/java/studio/one/platform/documentmetadata/BuiltInDocumentMetadataSchemaRegistryTest.java
```

[로컬 실증용 설정 초안](../examples/runner/studio-api-local.json)을 제공한다.

- 실제 확인한 repository ID, 3.x, 기준 SHA, 테스트 경로·명령을 반영했다.
- 원본 repo_path는 환경에 맞게 채운다. 개인 절대 경로는 예시에 넣지 않았다.
- execution=local이며 자동 게시할 수 없다. expires_at=0은 의도적인 실행 차단값이다.
- author ID 1과 reviewer-login은 로컬 작업용 임시 값이다. 실제 GitHub 계정으로 사용하지 않는다.
- 먼저 지침을 정리한 commit에서 baseline을 다시 고정해야 한다. 현재 SHA를 무조건 재사용하지 않는다.
- 기존 브랜치 규칙에 맞춰 feature/sanakan-{iid}, commit은 `[ai-assisted] test(document-metadata): ...`를 사용한다.
- 프로젝트의 PR 필수 항목과 한국어 기록을 publication에 반영했다. human review 체크는 자동 완료하지 않는다.

목표가 테스트 보강인 첫 이슈의 완료 조건은 다음 정도로 제한한다.

1. 위 테스트 파일만 변경하며 업무 코드/API/DB/빌드 설정을 변경하지 않는다.
2. 현재 구현의 경계값을 의미 있게 검증한다. 코드 변경이 필요하면 이유를 보고하고 멈춘다.
3. 선택한 단위 테스트와 기존 7개 검증이 모두 통과한다.
4. 독립 리뷰에서 차단 지적이 없고, 원본 작업공간에 새 변경이 없다.

작업 명세에는 대상 저장소의 Issue 분류(Type/Size/AI-Assisted)를 각각 하나씩 선택해 포함한다.
원격 이슈 없이 로컬 JSON으로 실행한 경우, 실제 GitHub 이슈를 만들었다고 기록하지 않는다.
검증 가능한 실제 개선 작업은 이 후보를 확정한 뒤 수행한다. 이번 검토에서는 Codex에 코드 수정을 맡기지 않았다.

## 4. Docker와 전달을 검증한다

운영 자동화로 전환하기 전에 [실행 경계 가이드](EXECUTION_BOUNDARY.md)를 따른다.

- Java 17, Gradle 8.14.5 및 선택 모듈 의존성을 승인 이미지에 준비한다.
- 검증 컨테이너는 network=none, root filesystem read-only, HOME=/tmp다.
- 호스트 Gradle/Maven 캐시를 사용한 이번 결과를 그대로 적용하지 않는다. 이미지의 의존성 복사와
  쓰기 가능한 Gradle cache/lock 경로를 정하고, tmpfs 512MB·메모리 2GB 제한 안에서 실행되는지 확인한다.
- 메인/개발/리뷰 컨테이너에는 model 연결만, 검증 컨테이너에는 모델 인증도 전달하지 않는다.
- 개발/게시 계정은 서로 다른 private runs와 인증된 packet 전달 경로를 사용한다.

현재 기준 commit의 실제 baseline.bundle 크기는 **12,433,045 bytes**였다.
이는 현행 exporter의 baseline bundle 상한 32MiB 이내지만, 전체 결과 packet/향후 이력 크기는 다시 확인한다.
크기만 확인했으며 실제 두 OS 계정의 전달·서명 키·디렉터리 권한 실증은 하지 않았다.

## 5. GitHub Draft PR 한 건으로 실증한다

로컬/Docker 단계가 통과한 뒤 [GitHub 가이드](GITHUB.md)로 진행한다.
실제 허용 작성자 ID, 리뷰어 login, 사전 승인 범위와 유효 기간, 분리된 토큰을 지정한다.
main이 아니라 승인한 3.x를 target으로 사용하고, 게시 직전에 원격 SHA를 다시 확인한다.

GitLab과 같은 규칙으로 Draft 상태를 유지하고 reviewer 요청 결과까지 확인한다.
GitHub가 이를 거절하면 성공으로 처리하거나 Draft를 임의 해제하지 않는다.
처음에는 자동화 대상 label을 `ai:ready` 등으로 좁혀 기존 열린 이슈 전체가 실행되지 않게 한다.

## 가이드에 반영할 운영 원칙

- 설치 성공보다 기존 지침의 목적·규칙 정합성을 먼저 확인한다.
- 원격 기본 브랜치와 실제 작업 기준 브랜치를 구분한다.
- 작은 모듈의 기준 테스트부터 확인하고 전체 테스트 성공과 구분한다.
- 로컬 캐시 성공, Docker 성공, GitHub 게시 성공을 각각 따로 기록한다.
- 프로젝트별 브랜치·commit·PR 형식을 읽어 설정에 반영한다.
- 정책 정리 → 로컬 개발 → 격리 실행 → 서명 전달 → Draft PR 순서로 범위를 넓힌다.
