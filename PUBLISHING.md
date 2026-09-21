# Git 게시 안내

## 1. 어떤 저장소에 올릴 것인가

이 폴더는 **자동화 코딩 도구의 Git 저장소의 루트**로 게시할 수 있다.
기존 RAG 애플리케이션 루트에 그대로 복사하는 용도가 아니다.
대상 프로젝트에 적용할 때는 templates와 docs의 필요한 내용만 기존 정책에 병합한다.

원격 주소·소유자·라이선스·공개 여부는 사용자가 결정한다. 이 패키지는 원격 저장소를 만들거나 게시하지 않는다.
GitHub와 GitLab 양쪽에서 Markdown을 읽을 수 있으며 패키지 자체 검증용 CI 예시가 루트에 포함된다.

GitLab에서는 Python 3.11+/Git/Bash를 포함한 검토된 digest 고정 이미지를
`GUIDE_VALIDATION_IMAGE` 변수에 설정해야 검증 job이 실행된다. GitHub 검증은 push/PR 시 실행된다.

## 2. 게시 전 확인

- [ ] 가이드 버전/원본 출처/수정 내용을 CHANGELOG에서 확인했다.
- [ ] 공개 게시라면 배포 권리와 LICENSE를 확정했다. LICENSE_NOTICE는 사용 허가서가 아니다.
- [ ] README의 실행 가능 도구와 미구현 자동화를 구분했다.
- [ ] python3 tools/validate_package.py 성공.
- [ ] PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v 성공.
- [ ] .env, token, 개인 경로, 실제 issue JSON, 로그, .git, build 산출물이 없음.
- [ ] CI image/action 버전 고정 정책을 조직 기준으로 검토했다.
- [ ] 원격 URL과 공개 범위를 사람이 확인했다.

## 3. 새 가이드 저장소에 게시하는 예

아래는 사람이 확인 후 실행하는 예이며 자동 실행되지 않는다.
실제 원격 URL로 바꾸고 인증정보는 URL에 넣지 않는다.

```sh
git init -b main
git add README.md VERSION CHANGELOG.md LICENSE LICENSE_NOTICE.md PUBLISHING.md VALIDATION.md
git add .gitignore .gitattributes .github .gitlab-ci.yml
git add 01_NEW_PROJECT_CHECKLIST.md 02_EXISTING_PROJECT_CHECKLIST.md 03_SECURITY_CHECKLIST.md
git add AGENTS.md sanakan plugins docs examples templates tests tools MANIFEST.txt SHA256SUMS
git diff --cached --check
git diff --cached --stat
git commit -m "[ai-assisted] docs(guide): 개발 운영 가이드 1.4.0 정리"
git remote add origin <사용자가-확인한-원격-URL>
git push -u origin main
```

조직이 Issue/Why/What/Validation을 포함한 commit 본문을 요구하면 해당 템플릿을 사용한다.
기존 저장소라면 위 git init/add를 그대로 실행하지 말고 작업 브랜치와 PR을 사용한다.
실제 실행기 사용과 GitLab 게시 단계는 [실행기 사용법](docs/RUNNER.md)을 따른다.
이 패키지의 templates/.gitlab-ci.codex.example.yml은 소비자 CI 예시이며 루트 CI와 역할이 다르다.

## 4. 수정본을 다시 배포할 때

1. 문서/도구를 수정하고 테스트를 실행한다.
2. VERSION, CHANGELOG, VALIDATION을 갱신한다.
3. `python3 tools/validate_package.py --refresh`로 MANIFEST/SHA256SUMS를 다시 생성한다.
4. `python3 tools/validate_package.py`로 변경 없이 재검증한다.
5. `python3 tools/build_release.py --output <패키지-밖의-새-ZIP-경로>`로 manifest 파일만 압축한다.
   이 명령은 기존 ZIP을 덮어쓰지 않는다. 검사값은 전송 손상을 탐지하지만 작성자 서명은 아니다.
