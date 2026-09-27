#!/usr/bin/env bash
# Oracle Cloud Ubuntu(22.04/24.04, ARM) 새 서버에서 한 번 실행한다.
#   bash deploy/oracle/setup.sh
# 하는 일: Docker 설치 → 80/443 포트 열기 → 스왑 4GB 추가.
set -euo pipefail

echo "[1/3] Docker 설치 (우분투 공식 저장소 패키지)"
sudo apt-get update -y
sudo apt-get install -y docker.io docker-compose-v2 iptables-persistent
sudo usermod -aG docker "$USER"

echo "[2/3] 방화벽: 80/443 허용"
# Oracle 우분투 이미지는 iptables에 기본 REJECT 규칙이 있어, 콘솔 보안 목록만 열면 접속이 안 된다.
# 기본 REJECT 규칙보다 앞(5번째)에 넣는다. 확인과 추가에 같은 규칙을 써야 다시 실행해도 중복되지 않는다.
for port in 80 443; do
  rule=(INPUT -p tcp -m state --state NEW --dport "$port" -j ACCEPT)
  if ! sudo iptables -C "${rule[@]}" 2>/dev/null; then
    sudo iptables -I "${rule[0]}" 5 "${rule[@]:1}"
  fi
done
sudo netfilter-persistent save

echo "[3/3] 스왑 4GB (LLM 모델 로딩 순간의 메모리 여유)"
if [ ! -f /swapfile ]; then
  sudo fallocate -l 4G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab
fi

echo
echo "완료. 다시 로그인한 뒤(도커 그룹 적용):"
echo "  cd deploy/oracle && cp .env.example .env && nano .env"
echo "  docker compose up -d --build"
echo "OCI 콘솔 > 네트워킹 > VCN > 보안 목록에서도 TCP 80, 443 수신을 허용해야 합니다."
