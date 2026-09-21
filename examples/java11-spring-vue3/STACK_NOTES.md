# Java 11 / Spring Boot 2.7 / Vue 3 적용 메모

역사적 스택 예시이며 현재 Studio 프로젝트의 설정이 아니다.
실제 적용은 docs/STUDIO_ADOPTION.md와 대상 프로젝트 기준선을 우선한다.
버전 업그레이드를 이 템플릿 적용과 묶어 수행하지 않는다.

사용자 환경 예시:

- Java 11
- Spring Boot 2.7.18
- Gradle 8.x
- Spring Security 5.7.x
- MyBatis 또는 JPA
- PostgreSQL 또는 MySQL
- Vue 3 / Vite / Vuetify 3 / Pinia / AG Grid

## 권장 검증

Backend:

```bash
./gradlew clean test
```

Frontend:

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

## 특히 자동 구현에서 제외할 영역

- JWT 발급·재발급·grace 정책
- SecurityFilterChain과 권한 매핑
- 사용자·역할·그룹 스키마
- Flyway
- 파일 저장 base-dir
- 운영 배포 WAR/JBoss 설정
- Redis·STOMP 멀티서버 설정
- 공통 Axios 재발급 큐
- Router role 정책

## 첫 실증에 적합한 작업

- 입력값 검증
- 오류 메시지
- 조회 조건
- 빈 데이터 화면
- AG Grid 컬럼·표시 오류
- 중복 요청 방지
- 단위테스트 보완
