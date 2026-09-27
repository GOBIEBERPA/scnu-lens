# Oracle Cloud 서버 설치 (API · 수집 · 알림)

Ubuntu 24.04(ARM64 또는 x86_64), Caddy가 설치된 서버 한 대에 SCNU Lens 백엔드와 화면을 올린다.
서버의 다른 서비스는 건드리지 않고, Caddyfile에는 이 앱 블록 하나만 끝에 추가한다(추가 전 자동 백업).

## 구성

| 항목 | 값 |
|---|---|
| 계정 | `scnulens` (로그인 불가 시스템 계정) |
| 코드 | `/opt/scnu-lens/backend`, `/opt/scnu-lens/frontend` |
| 파이썬 / Node | `/opt/scnu-lens/venv` (Python 3.12) / `/opt/node` (v22, SHA256 확인 후 설치) |
| DB | `/opt/scnu-lens/data/scnu_lens.db` (SQLite) |
| 설정 | `/opt/scnu-lens/backend/.env` (0600). 관리자 키·VAPID 키는 설치 때 서버에서 새로 생성 |
| 서비스 | `scnu-lens-api` → 127.0.0.1:8100 (메모리 상한 1.5GB), `scnu-lens-web` → 127.0.0.1:3100 (512MB) |
| https | Caddy: `/api/*` → 8100, 나머지 → 3100. 기본 주소 `scnu.64-110-105-215.sslip.io` |

## 설치 · 갱신

```bash
cd ~/scnu-lens                          # 이 저장소
sudo bash deploy/oracle-sslip/install.sh
# 주소 바꾸기: sudo SCNU_HOST=다른이름.<IP>.sslip.io bash deploy/oracle-sslip/install.sh
```

- 순서: 패키지 → Node 22 → 계정·코드 복사 → venv·pip → `.env` 생성(처음 한 번) → `npm ci && npm run build` → systemd → Caddy
- 첫 실행은 5~10분(onnxruntime 설치, Next 빌드). 다시 실행하면 코드만 갱신하고 서비스를 재시작하며 `.env`·DB는 그대로 둔다.

## 공공데이터 키 넣기

```bash
sudo nano /opt/scnu-lens/backend/.env      # DATA_GO_KR_KEY= 뒤에 일반 인증키(Decoding)
sudo systemctl restart scnu-lens-api
```

## 확인 · 운영

| 할 일 | 명령 |
|---|---|
| 상태 | `systemctl status scnu-lens-api scnu-lens-web` |
| 헬스 체크 | `curl -s http://127.0.0.1:8100/api/health` |
| 로그 | `sudo journalctl -u scnu-lens-api -f` |
| 즉시 수집 | 관리자 화면(`/admin`)의 "지금 수집" 또는 `X-Admin-Key` 헤더로 `POST /api/admin/crawl` |
| 규칙 재적용 | `cd /opt/scnu-lens/backend && sudo -u scnulens ../venv/bin/python -m scripts.restructure` |
| 백업 | `/opt/scnu-lens/data/scnu_lens.db` 파일 하나 |

## 되돌리기

```bash
sudo systemctl disable --now scnu-lens-api scnu-lens-web
sudo rm /etc/systemd/system/scnu-lens-{api,web}.service && sudo systemctl daemon-reload
# Caddyfile에서 이 앱 블록 삭제(설치 때 만든 /etc/caddy/Caddyfile.bak-날짜 참고) → sudo systemctl reload caddy
sudo rm -rf /opt/scnu-lens && sudo userdel scnulens
```

## 화면 배포 (Vercel)

`frontend/`를 Vercel에 배포한다. `frontend/vercel.json`이 `/api/*` 요청을 이 서버로 넘긴다.
서버 주소를 바꿨다면 `vercel.json`의 `destination`도 바꾼다.
