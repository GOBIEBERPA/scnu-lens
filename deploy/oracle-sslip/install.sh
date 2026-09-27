#!/usr/bin/env bash
# SCNU Lens를 이미 Caddy가 돌고 있는 Oracle 서버(Ubuntu 24.04, ARM64)에 올린다. 다시 실행하면 코드만 갱신한다.
#
#   저장소 루트에서:  sudo bash deploy/oracle-sslip/install.sh
#   주소 바꾸기:      sudo SCNU_HOST=다른이름.64-110-105-215.sslip.io bash deploy/oracle-sslip/install.sh
#
# 서버 관례를 따른다: 전용 계정(scnulens) + /opt/scnu-lens + systemd(127.0.0.1) + Caddy https.
# 비밀값은 서버에서 새로 만든다(관리자 키·VAPID). 공공데이터 키만 설치 뒤 .env에 직접 넣는다.
set -euo pipefail

HOST="${SCNU_HOST:-scnu.64-110-105-215.sslip.io}"
APP_USER=scnulens
DIR=/opt/scnu-lens
API_PORT=8100
WEB_PORT=3100
SRC="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$SRC/deploy/oracle-sslip"
NODE_DIR=/opt/node
export PATH="$NODE_DIR/bin:$PATH"

[ "$(id -u)" -eq 0 ] || { echo "sudo로 실행하세요: sudo bash $0"; exit 1; }
[ -f "$SRC/backend/requirements.txt" ] || { echo "저장소 루트를 찾지 못했습니다: $SRC"; exit 1; }

step() { printf '\n== %s\n' "$1"; }

# 다른 서비스가 이미 쓰는 포트면 멈춘다(우리 서비스가 쓰는 건 괜찮음 — 재설치).
for port in "$API_PORT" "$WEB_PORT"; do
  owner="$(ss -ltnpH "sport = :$port" 2>/dev/null | grep -o 'users:(("[^"]*"' | head -1 || true)"
  if [ -n "$owner" ] && ! systemctl is-active --quiet scnu-lens-api scnu-lens-web; then
    echo "포트 $port 를 이미 다른 프로그램이 쓰고 있습니다: $owner"; exit 1
  fi
done

step "1/8 패키지"
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip rsync curl xz-utils openssl >/dev/null

step "2/8 Node.js 22 (공식 배포본, SHA256 확인)"
if ! "$NODE_DIR/bin/node" -v 2>/dev/null | grep -q '^v22\.'; then
  case "$(uname -m)" in
    aarch64) arch=linux-arm64 ;;
    x86_64) arch=linux-x64 ;;
    *) echo "지원하지 않는 CPU: $(uname -m)"; exit 1 ;;
  esac
  base=https://nodejs.org/dist/latest-v22.x
  sums="$(curl -fsSL "$base/SHASUMS256.txt")"
  file="$(awk -v a="$arch.tar.xz" '$2 ~ a"$" {print $2; exit}' <<<"$sums")"
  sum="$(awk -v f="$file" '$2 == f {print $1; exit}' <<<"$sums")"
  curl -fsSLo "/tmp/$file" "$base/$file"
  echo "$sum  /tmp/$file" | sha256sum -c -
  rm -rf "$NODE_DIR" && mkdir -p "$NODE_DIR"
  tar -xJf "/tmp/$file" -C "$NODE_DIR" --strip-components=1
  rm -f "/tmp/$file"
fi
node -v

step "3/8 전용 계정·코드 복사"
id "$APP_USER" &>/dev/null || useradd --system --home-dir "$DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$DIR/data" "$DIR/.cache"
# .env·DB·빌드 결과는 덮어쓰지도 지우지도 않는다(--delete는 제외 대상은 건드리지 않음).
rsync -a --delete --exclude '.env' --exclude '*.db' --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  "$SRC/backend/" "$DIR/backend/"
rsync -a --delete --exclude 'node_modules' --exclude '.next' --exclude '.env*' \
  "$SRC/frontend/" "$DIR/frontend/"

step "4/8 파이썬 가상환경·라이브러리"
[ -x "$DIR/venv/bin/python" ] || python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
"$DIR/venv/bin/pip" install -q -r "$DIR/backend/requirements.txt"

step "5/8 설정 파일(.env) — 처음 한 번만 만든다"
ENV_FILE="$DIR/backend/.env"
if [ ! -f "$ENV_FILE" ]; then
  vapid="$("$DIR/venv/bin/python" "$DIR/backend/scripts/gen_vapid.py" | grep '^VAPID_')"
  umask 077
  cat > "$ENV_FILE" <<EOF
APP_ENV=production
DATABASE_URL=sqlite:///$DIR/data/scnu_lens.db
FRONTEND_ORIGIN=https://$HOST
ADMIN_API_KEY=$(openssl rand -hex 24)
SCHEDULER_ENABLED=true
CRAWL_CRON_HOURS=*
NOTICE_RETENTION_DAYS=30
LLM_ENABLED=false
VAPID_SUBJECT=mailto:scnu-lens@example.com
$vapid
# 공공데이터포털 인증키(큐넷·데이터 자격검정·K-Startup). 비워 두면 학교 공지만 수집한다.
DATA_GO_KR_KEY=
EOF
  NEW_ENV=1
else
  NEW_ENV=0
fi
chown -R "$APP_USER:$APP_USER" "$DIR"
chmod 600 "$ENV_FILE"

step "6/8 화면 빌드(Next.js)"
sudo -u "$APP_USER" env PATH="$PATH" HOME="$DIR" NEXT_TELEMETRY_DISABLED=1 bash -c \
  "cd '$DIR/frontend' && npm ci --no-audit --no-fund --loglevel=error && npm run build"

step "7/8 systemd 서비스"
install -m 644 "$HERE/scnu-lens-api.service" /etc/systemd/system/scnu-lens-api.service
install -m 644 "$HERE/scnu-lens-web.service" /etc/systemd/system/scnu-lens-web.service
systemctl daemon-reload
systemctl enable scnu-lens-api scnu-lens-web >/dev/null
systemctl restart scnu-lens-api scnu-lens-web

step "8/8 Caddy(https) — 이미 있으면 건드리지 않는다"
CADDYFILE=/etc/caddy/Caddyfile
if ! grep -q "^$HOST" "$CADDYFILE"; then
  cp "$CADDYFILE" "$CADDYFILE.bak-$(date +%Y%m%d%H%M%S)"
  { echo; sed "s/__HOST__/$HOST/" "$HERE/Caddyfile.snippet"; } >> "$CADDYFILE"
  caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null
  systemctl reload caddy
fi

echo
echo "상태 확인(백엔드는 AI 모델을 받느라 처음엔 1~2분 걸릴 수 있음)"
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1; then echo "API 정상"; break; fi
  sleep 3
done
systemctl --no-pager --lines=0 status scnu-lens-api scnu-lens-web | grep -E '●|Active:'
echo
echo "주소: https://$HOST  (인증서 발급에 1분 정도 걸릴 수 있음)"
if [ "$NEW_ENV" -eq 1 ]; then
  echo
  echo "다음 할 일: 공공데이터 키 넣기"
  echo "  sudo nano $ENV_FILE        # DATA_GO_KR_KEY= 뒤에 키 붙여넣기"
  echo "  sudo systemctl restart scnu-lens-api"
fi
