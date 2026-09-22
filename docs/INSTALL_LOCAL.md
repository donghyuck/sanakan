# 내 Git 프로젝트에서 시작하기

**기존 로컬 프로젝트를 지정하고, 할 일을 적은 뒤 실행하면 됩니다.**
Sanakan이 별도 작업공간에서 코드를 수정하고 테스트·리뷰한 결과를 남깁니다.
GitLab 연결은 나중에 합니다.

준비할 것은 다음 세 가지입니다.

- 로컬에 있는 Git 프로젝트
- 인증된 Codex CLI와 Python 3.11 이상, Git, Bash가 있는 Linux/macOS 환경
- 해당 프로젝트를 빌드·테스트할 도구와 의존성

대상 프로젝트에 Sanakan을 복사하거나 `AGENTS.md`를 바꿀 필요는 없습니다.
**현재 commit을 기준으로 작업하므로, 아직 commit하지 않은 변경은 포함되지 않습니다.**

## 1. 경로 지정하기

터미널에서 아래 **네 경로를 내 환경에 맞게 바꿔서** 실행합니다.
설정과 결과 폴더는 Sanakan과 대상 프로젝트 밖에 둡니다.
이후 명령도 같은 터미널에서 실행하세요.

```sh
cd "/path/to/sanakan"
export SANAKAN_SOURCE="/path/to/my-project"
export SANAKAN_SETTINGS="/path/to/sanakan-settings"
export SANAKAN_RUNS="/path/to/sanakan-runs"

mkdir -p "$SANAKAN_SETTINGS" "$SANAKAN_RUNS"
git -C "$SANAKAN_SOURCE" status --short
```

| 경로 | 용도 |
|---|---|
| `cd` 뒤의 경로 | Sanakan 도구 위치 |
| `SANAKAN_SOURCE` | 이미 로컬에 있는 내 Git 프로젝트 |
| `SANAKAN_SETTINGS` | 설정과 할 일을 적어둘 폴더 |
| `SANAKAN_RUNS` | 작업 결과를 저장할 폴더 |

마지막 명령에 파일이 표시되면 미커밋 변경이 있는 것입니다.
그 변경까지 작업에 필요하다면 먼저 검토해 commit하세요. Sanakan이 대신 commit하지는 않습니다.

## 2. 설정 파일 만들기

처음 설정할 때 아래 블록을 그대로 실행합니다.
예시 파일을 복사하고 프로젝트 경로·현재 commit·1시간의 실행 승인 유효 기간을 채웁니다.

```sh
cp -n examples/runner/local-project.json "$SANAKAN_SETTINGS/project.json"
cp -n examples/runner/local-issue.json "$SANAKAN_SETTINGS/issue.json"

python3 - <<'PY'
import json
import os
from pathlib import Path
import subprocess
import time

source = Path(os.environ['SANAKAN_SOURCE']).resolve(strict=True)
settings = Path(os.environ['SANAKAN_SETTINGS'])
path = settings / 'project.json'
config = json.loads(path.read_text())
config['repo_path'] = str(source)
config['baseline'] = subprocess.check_output(
    ['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
config['expires_at'] = int(time.time()) + 3600
path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
PY
```

이제 설정 폴더의 **두 파일만 편집**합니다.

**`project.json`: 어디를 수정하고, 어떻게 검사할지**

- `allowed_paths`: 수정할 수 있는 파일 경로. 폴더나 `*` 대신 정확한 파일명을 적습니다.
- `checks`: 이 프로젝트에서 반드시 실행할 테스트·빌드 명령을 적습니다.

예를 들어 Gradle 프로젝트라면 해당 두 항목을 다음처럼 바꿀 수 있습니다.
파일 경로는 실제 작업에 맞게 바꾸세요.

```json
"allowed_paths": ["src/main/java/example/Price.java", "src/test/java/example/PriceTest.java"],
"checks": [{"id": "backend", "argv": ["bash", "./gradlew", "test", "build"]}]
```

`argv`는 명령을 띄어쓰기 단위로 나눈 목록입니다.
위 예시는 `bash ./gradlew test build`를 실행합니다. 검증 명령은 프로젝트 루트에서 실행됩니다.

**`issue.json`: 무엇을 고칠지**

`title`과 `description`을 실제 작업 내용으로 바꿉니다. 예시 설명을 그대로 두고 실행하지 마세요.

```json
"title": "수량이 0일 때 가격 계산 오류 수정",
"description": "현재 수량이 0이면 예외가 발생한다. 수량이 0이면 합계 0을 반환하도록 수정한다. 정상 수량 계산은 유지하고, 수량 0 테스트를 추가한다."
```

두 예시는 파일 전체가 아니라 **교체할 항목**입니다. 나머지 항목은 우선 그대로 둡니다.
특히 `local.invalid` 주소나 숫자 ID는 실제 GitLab 정보로 바꿀 필요가 없습니다.

## 3. 실행하기

설정을 마쳤으면 아래 명령을 그대로 실행합니다.

```sh
env -u SANAKAN_READ_TOKEN -u SANAKAN_PUBLISH_TOKEN \
  python3 -m sanakan run \
  --config "$SANAKAN_SETTINGS/project.json" \
  --issue https://local.invalid/local/project/-/issues/1 \
  --issue-fixture "$SANAKAN_SETTINGS/issue.json" \
  --runs "$SANAKAN_RUNS"
```

`--issue-fixture`는 **GitLab 대신 내가 작성한 작업 파일을 읽으라**는 뜻입니다. 빼지 마세요.
GitLab 토큰은 필요 없지만, 실제 Codex를 실행하므로 Codex 인증과 모델 접근은 필요합니다.

```text
작업 이해 → 코드 수정 → 테스트 → 독립 리뷰 → 필요하면 재수정 → 결과 저장
```

## 4. 결과 확인하기

실행 결과의 `status`를 확인합니다.

| 상태 | 뜻 | 다음 행동 |
|---|---|---|
| `ready` | 검증과 리뷰를 통과함 | 변경된 코드를 확인 |
| `needs_human` | 추가 설명이나 판단이 필요함 | `reason`과 `questions` 확인 |
| `failed` | 실행 중 오류 발생 | `reason`과 로그 확인 |

결과 폴더 안에서 다음 파일을 찾으면 됩니다.

```text
<작업 폴더>/state.json                   현재 상태와 최종 attempt 번호
<작업 폴더>/attempt-번호/change.patch    코드 변경 내용
<작업 폴더>/attempt-번호/verification.json  테스트 결과
<작업 폴더>/attempt-번호/review.json     리뷰 결과
```

**첫 테스트는 `ready`와 변경 내용을 확인하면 완료입니다.**
원본 프로젝트에 수정 사항을 자동 반영하거나 commit·push하지 않습니다.
로컬 테스트에서는 `publish`를 실행하지 않습니다.

## 막힐 때 확인할 것

| 상황 | 확인할 내용 |
|---|---|
| 설정이 만료됐다고 나옴 | 준비한 설정은 1시간 유효. 새 작업의 설정을 다시 준비 |
| 수정할 파일이 허용되지 않음 | `allowed_paths`에 정확한 상대 파일 경로가 있는지 확인 |
| 빌드 도구나 의존성을 찾지 못함 | 새 작업공간에는 원본의 node_modules·미커밋 설정이 복사되지 않음. 필요한 설치 명령을 checks에 추가 |
| 다시 실행해도 이전 결과가 나옴 | 같은 작업은 중복 실행하지 않음. 설정/작업을 고쳤다면 새 결과 폴더를 지정 |

설정이 시작된 작업의 기록을 덮어쓰지 않도록, 다시 테스트할 때는 새 설정·결과 폴더를 사용하세요.
설정/작업을 수정했다면 `issue.json`의 `updated_at`도 수정 시각으로 갱신합니다.

<details>
<summary>현재 버전의 제약과 다음 단계</summary>

- Git 원격 주소가 없어도 로컬 테스트가 가능합니다.
- 설정에 남아 있는 GitLab 형식 필드는 현재 실행기의 필수 항목입니다. 로컬 테스트에서는 임시 값으로 유지합니다.
- `target_branch: main`은 로컬 테스트에서 형식만 검사하며 실제 main 브랜치가 없어도 됩니다.
- 실행 중인 프로세스의 자동 재개와 작업 결과의 원본 반영은 아직 제공하지 않습니다.
- 사용자 셸의 임의 환경변수는 검증 프로세스에 전달되지 않습니다. 빌드 도구와 환경은 미리 준비하세요.
- 별도 작업공간은 원본을 보존하지만 보안 격리를 대신하지는 않습니다. 운영 비밀이 없는 개발 환경에서 실행하세요.
- 로컬 테스트 결과는 MR로 게시할 수 없습니다. 로컬 실증 후 [GitHub](GITHUB.md) 또는 [GitLab](RUNNER.md) 연동 가이드에 따라 새 작업을 실행합니다.
- 모델 호출 없는 도구 자체 테스트는 [README의 로컬 검증](../README.md#로컬-검증)을 참고하세요.

</details>
