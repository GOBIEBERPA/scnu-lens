# SCNU Lens 오라클 서버 배포 인계 문서

> 작성: 2026-09-27, 학교 PC(WORKPC)의 Claude Code 대화에서 정리.
> 받는 쪽: 집 PC의 Claude Code. 이 PC에 오라클 서버 SSH 키가 있다.
> 이 문서에는 비밀값이 없다. 서버에서 새로 만들거나, 사용자가 서버 파일에 직접 넣는다.

## 0. 목표

오라클 서버(`ssh ubuntu@64.110.105.215`)에 SCNU Lens를 올려서
**https://scnu.64-110-105-215.sslip.io** 로 누구나 접속하게 한다. 이 주소는 해커톤 제출용 앱 주소로도 쓴다.

서버에 이미 있는 것은 **절대 건드리지 않는다**: 마인크래프트, ds-chat, mc-status, trading-monitor.
Caddyfile은 **끝에 블록 하나만 추가**한다(설치 스크립트가 백업 후 추가).

## 1. SCNU Lens가 무엇인가

순천대 공지·공모전·자격증 알리미(2026 SCNU OSS·AI 해커톤 출품작).

- **백엔드**: FastAPI + SQLite + APScheduler
  - 매시간 순천대 게시판 109곳 수집(학교 사이트만, scnu.ac.kr 외 주소는 코드에서 차단)
  - 공공데이터포털 API: 큐넷 시험일정, 데이터 자격검정, K-Startup
  - fastembed 임베딩 모델(paraphrase-multilingual-MiniLM, 약 220MB)로 분류
  - 매일 마감 D-7·3·1 알림, 1분마다 접수 시작·마감 시각 알림(웹 푸시 + 앱 알림함)
- **화면**: Next.js 16(PWA). https로 열리면 같은 주소의 `/api`를 부른다.
- **자원**: RAM 약 1GB(AI 모델 포함 백엔드 약 750MB + 화면 약 80MB), CPU 거의 0%(수집 중에도 한 자릿수 %)
  - 서버 여유 3.4GB 안에 충분히 들어간다.
  - systemd로 백엔드 1.5GB, 화면 512MB 상한을 걸어 마크 서버를 보호한다.
  - 로컬 LLM(Ollama)은 쓰지 않는다(`LLM_ENABLED=false`).

## 2. 배포 구성(서버 관례 그대로)

| 항목 | 값 |
|---|---|
| 리눅스 계정 | `scnulens` (로그인 불가 시스템 계정) |
| 코드 | `/opt/scnu-lens/backend`, `/opt/scnu-lens/frontend` |
| 파이썬 | `/opt/scnu-lens/venv` (Ubuntu 기본 Python 3.12) |
| Node.js | `/opt/node` (공식 v22 arm64 배포본, SHA256 확인 후 설치) |
| DB | `/opt/scnu-lens/data/scnu_lens.db` (SQLite) |
| 설정 | `/opt/scnu-lens/backend/.env` (0600). 관리자 키·VAPID 키는 설치 때 서버에서 새로 생성 |
| 서비스 | `scnu-lens-api` → 127.0.0.1:**8100**, `scnu-lens-web` → 127.0.0.1:**3100** |
| Caddy | `scnu.64-110-105-215.sslip.io` 블록 추가: `/api/*` → 8100, 나머지 → 3100 |
| 방화벽 | 80/443이 이미 열려 있어서 작업 없음. 8100/3100은 127.0.0.1 전용이라 외부 노출 없음 |

파일(이 폴더): `install.sh`, `scnu-lens-api.service`, `scnu-lens-web.service`, `Caddyfile.snippet`

## 3. 배포 순서

### 3-1. 코드를 서버로 옮기기(둘 중 하나)
- **GitHub에 공개로 올렸다면**(해커톤 제출용 저장소):
  `ssh ubuntu@64.110.105.215` → `git clone https://github.com/<계정>/<저장소>.git ~/scnu-lens`
- **폴더로 받았다면**(USB, 클라우드 등으로 집 PC에 `SCNU-Lens-GitHub업로드` 폴더를 옮긴 경우):
  집 PC에서 `scp -r <폴더> ubuntu@64.110.105.215:~/scnu-lens`
  - 이 폴더에는 `.env`와 DB가 없다(학교 PC에서 보안 점검 완료). 받은 폴더에 `.env`나 `*.db`가 있으면 올리지 말 것.

### 3-2. 설치
```bash
cd ~/scnu-lens
sudo bash deploy/oracle-sslip/install.sh
```
- 설치 내용: 패키지 → Node 22 → 계정·코드 복사 → venv·pip → .env 생성 → `npm ci && npm run build` → systemd → Caddy
- 첫 실행은 pip(onnxruntime 등)와 Next 빌드 때문에 5~10분 걸린다.
- 다시 실행하면 코드만 갱신하고 서비스를 재시작한다. `.env`와 DB는 그대로 둔다.

### 3-3. 공공데이터 키 넣기(사용자가 직접)
```bash
sudo nano /opt/scnu-lens/backend/.env      # DATA_GO_KR_KEY= 뒤에 붙여넣기
sudo systemctl restart scnu-lens-api
```
- 키는 data.go.kr → 마이페이지 → 개발계정 → **일반 인증키(Decoding)**.
- 키는 채팅에 붙여넣지 말고 서버 파일에 직접 넣는다.
- 이 키로 쓸 수 있게 승인된 API: 국가자격 시험일정, 데이터 자격검정 시험 정보, K-Startup.

### 3-4. 첫 수집 바로 돌리기(안 하면 다음 정각에 자동 수집)
관리자 키를 화면에 출력하지 않고 서버 안에서만 읽는다.
```bash
sudo bash -c 'k=$(grep ^ADMIN_API_KEY= /opt/scnu-lens/backend/.env | cut -d= -f2); curl -s -m 900 -X POST -H "X-Admin-Key: $k" http://127.0.0.1:8100/api/admin/crawl' | head -c 400
```
- 처음에는 게시판마다 상세 글까지 받아서 몇 분 걸린다. 결과 JSON의 `fetched`, `inserted`, `structured` 숫자를 확인한다.

## 4. 확인
- [ ] `systemctl status scnu-lens-api scnu-lens-web` 가 둘 다 active
- [ ] `curl -s http://127.0.0.1:8100/api/health` 에 `"status":"ok"`
- [ ] 브라우저로 https://scnu.64-110-105-215.sslip.io 열기: 학교 탭과 공모전·자격증 탭에 공지가 보임
- [ ] 휴대폰에서 알림 켜기 → 테스트 알림 도착
  - iOS는 홈 화면에 추가한 뒤에만 됨
- [ ] `free -h`: 마크 서버 포함 여유 메모리가 남아 있는지(목표: 사용 약 9.5GB 이하)
- [ ] https://sys.64-110-105-215.sslip.io 현황 페이지에서 서비스별 메모리 확인
  - mc-status가 서비스 목록을 고정해 두었다면 scnu-lens 두 개를 추가하는 것은 선택

## 5. 운영
| 할 일 | 명령 |
|---|---|
| 로그 | `sudo journalctl -u scnu-lens-api -f` / `-u scnu-lens-web` |
| 재시작 | `sudo systemctl restart scnu-lens-api scnu-lens-web` |
| 코드 갱신 | 새 코드로 `~/scnu-lens` 갱신 → `sudo bash deploy/oracle-sslip/install.sh` |
| 관리자 화면 | https://scnu.64-110-105-215.sslip.io/admin (키: 서버 `.env`의 ADMIN_API_KEY. 사용자가 직접 확인) |
| 백업(선택) | `/opt/scnu-lens/data/scnu_lens.db` 한 파일. 마크 백업 cron과 같은 방식으로 추가 가능 |

## 6. 되돌리기(완전히 빼기)
```bash
sudo systemctl disable --now scnu-lens-api scnu-lens-web
sudo rm /etc/systemd/system/scnu-lens-{api,web}.service && sudo systemctl daemon-reload
# Caddyfile에서 scnu.64-110-105-215.sslip.io 블록 삭제(설치 때 /etc/caddy/Caddyfile.bak-날짜 백업 있음) → sudo systemctl reload caddy
sudo rm -rf /opt/scnu-lens && sudo userdel scnulens      # /opt/node는 다른 앱이 안 쓰면 삭제 가능
```

## 7. 주의
- **학교 PC(WORKPC)에서도 같은 앱이 돌고 있다.**
  - 작업 스케줄러 "SCNU Lens", 주소 `desktop-sqi0657.tailc09694.ts.net`
  - 오라클이 잘 돌면 학교 PC에서 `stop-scnu-lens.ps1`로 끄고 작업 스케줄러 "SCNU Lens"를 사용 안 함으로 바꾼다. 학교 게시판 중복 수집을 막기 위해서다.
  - DB가 따로라 알림이 같은 휴대폰으로 두 번 가지는 않는다. 다만 양쪽에서 모두 알림을 켠 휴대폰은 예외.
- 공지 주소가 바뀌어서 휴대폰 알림은 **새 주소에서 다시 켜야** 한다(VAPID 키도 새로 만들었으므로).
- 오라클 A1 무료 한도(2 OCPU/12GB)는 기존 인스턴스가 이미 다 쓰고 있다. 이 앱은 **같은 인스턴스 안에** 올리므로 추가 과금이 없다. 인스턴스를 새로 만들지 말 것.
- 문제가 생기면 먼저 `journalctl`의 에러를 보고 원인을 잡는다. 자주 막히는 곳:
  - pip의 onnxruntime(ARM 휠)
  - HuggingFace 모델 다운로드(첫 분류 때)
  - Caddy 인증서 발급(1분 대기)
