# 1.5 실행 격리와 결과 전달

이 문서는 1.4 검토에서 발견한 문제를 해결하는 운영 계약이다.
로컬 개발 테스트와 자동 게시 가능한 실행을 구분한다.

## 로컬 개발 테스트

`execution`이 없거나 `{"backend":"local"}`이면 기존 `run --issue-fixture`를 사용할 수 있다.
현재 commit을 별도 작업공간으로 가져와 실제 Codex 개발·검증·리뷰를 수행한다.
검증 명령은 호스트 프로세스이므로 신뢰된 임시 코드만 사용한다.
**로컬 실행 결과는 export/publish할 수 없으며 watch/start도 사용할 수 없다.**

## 자동 개발 실행

자동화 설정에는 다음 항목이 필요하다.

```json
"execution": {
  "backend": "docker",
  "image": "registry.example.com/sanakan-runner@sha256:<실제 이미지 digest>",
  "agent_network": "sanakan-model-egress"
}
```

운영자가 미리 준비할 것:

- 실행 중인 Docker Engine과 승인된 digest 고정 이미지. 이미지는 자동 pull하지 않는다.
- 이미지 안의 Codex CLI, Git, Python 및 프로젝트의 빌드 도구/의존성.
- 모델 API만 접근하도록 호스트에서 통제하는 전용 네트워크. **네트워크 이름만으로 방화벽 정책이 생기지는 않는다.**
- 개발 조정기에서 사용할 Codex auth.json 또는 OPENAI_API_KEY. auth 경로는 SANAKAN_CODEX_AUTH_FILE로 지정할 수 있다.
- 서로 다른 개발/게시 계정과 각자의 비공개 설정·소스·run 저장소.

메인/리뷰의 workspace mount는 읽기 전용이고, 개발 workspace만 쓰기 가능하다.
검증도 별도 컨테이너에서 실행하며 network=none이고 모델 인증을 전달하지 않는다.
호스트 HOME, Docker socket, 정책 파일, run 상태, 전달 서명 키는 컨테이너에 mount하지 않는다.
root filesystem은 읽기 전용이고 non-root UID, capability 제거, no-new-privileges,
PID 256개·메모리 2GB·CPU 2개 제한을 적용한다. 임시 파일은 /tmp tmpfs에 쓴다.
컨테이너 내부 Codex는 중첩 sandbox 대신 외부 Docker 경계를 사용한다.
기존 로컬 Codex adapter는 sandbox 우회 플래그를 사용하지 않는다.

검증 명령의 경로는 컨테이너 안에서 유효해야 한다. 의존성은 이미지에 준비하고
생성 산출물은 Git ignore 규칙에 맞게 설정한다. tracked 파일/승인된 patch의 소스나
미무시 파일이 검증 중 달라지면 종료 코드가 0이어도 실패한다.
각 명령 사이에 중지 요청도 확인한다. timeout 이후에는 Docker client뿐 아니라 컨테이너도 제거한다.

## 결과는 서명된 파일로 전달

```text
개발 계정의 private runs (0700)
       ↓ export: patch + 검증/리뷰 + 기준 Git bundle, HMAC-SHA256 인증
프로젝트 전용 전달 디렉터리 (packet 0640)
       ↓ import: 서명/정책/gate 검사
게시 계정의 private runs (0700)
       ↓ 이슈·기준 브랜치·원격 결과 재확인
GitLab Draft MR
```

개발/게시 프로세스가 같은 jobs.json을 수정하지 않는다. 서로 다른 `--runs`를 사용한다.
공유 디렉터리는 개발 계정이 쓰고 게시 계정은 읽을 수 있게 setgid/그룹 권한으로 준비한다.
서명은 암호화가 아니므로 packet에 담긴 코드와 이슈를 읽을 수 있는 계정도 제한한다.
HMAC 키는 같은 랜덤 bytes를 각 신뢰 계정의 별도 파일에 두고 chmod 600으로 보호한다.
이 키는 모델/검증 프로세스에 전달하지 않는다. 양쪽 신뢰 계정은 서로 신뢰하는 주체다.

각 계정에서 다음 환경변수를 지정한다. 키 값 자체는 환경변수나 명령행에 넣지 않는다.

```sh
export SANAKAN_HANDOFF_DIR=/var/spool/sanakan-project
export SANAKAN_HANDOFF_KEY_FILE=/protected/handoff.key
```

개발 계정의 watch는 ready 결과를 자동 export한 뒤 `handed_off`로 표시한다.
게시 계정의 watch는 signed packet을 import해 ready → published로 처리한다.
개발 상태와 최종 MR 상태는 각각의 run 저장소에서 조회한다. 양방향 상태 동기화는 아직 없다.
서명·정책이 맞지 않는 packet은 실행하지 않고 `status`의 `handoff_errors`에 이유를 남긴다.
기준 commit은 bundle로 전달하므로 게시기가 개발 계정의 소스 폴더를 읽을 필요가 없다.

수동 전달도 가능하다.

```sh
# 개발 계정: isolated run이 ready인 경우
python3 -m sanakan export --config /protected/project.json \
  --issue https://gitlab.example.com/team/project/-/issues/123 --runs /var/lib/sanakan-develop

# 게시 계정: 자신의 설정(repo_path는 자신의 clone)과 private runs 사용
python3 -m sanakan import --config /protected/project.json \
  --packet /var/spool/sanakan-project/<digest>.sanakan.json --runs /var/lib/sanakan-publish
```

수동 import 결과의 `config` 경로를 publish의 `--config`로 사용한다.
자동 감시기는 이 경로를 내부에서 연결한다. bundle을 포함한 packet 크기는 64MB로 제한하며
큰 저장소는 전송 방식/한도를 별도 설계해야 한다. 승인되지 않은 파일명·symlink packet·변조 서명은 거절한다.

## 게시 재시도와 재검증

- 일시적 HTTP 오류: 기존 결과를 재게시한다. 기존 branch/MR부터 확인한다.
- 이슈/기준 브랜치/정책 변경: `needs_revalidation` 또는 handoff_errors로 중단한다.
- 양쪽 감시기를 중지하고 running=false를 확인한 뒤 개발 계정에서 `retry --iid 123 --mode revalidate`를 실행하면 새 generation과 기준 commit으로 다시 개발·검증한다.
- 게시 계정은 재개발하지 않는다. 새 signed packet을 기다린다.
- 기존 원격 branch/MR이 남아 있으면 임의 삭제·force push하지 않고 사람이 정리 여부를 판단한다.

이전에 만든 1.4 ready 결과는 그대로 자동 게시하지 않는다. 1.5 설정으로 재실행한다.
Docker Engine, 승인 이미지와 네트워크 정책의 실환경 동작은 별도 확인해야 한다.
이번 환경에서는 Docker 데몬이 연결되지 않아 실제 컨테이너 실행은 미검증이다.
