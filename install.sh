#!/usr/bin/env bash
set -euo pipefail

APP_NAME="dbonline-media-stack"
INSTALL_DIR="/opt/${APP_NAME}"
REPO_URL="${REPO_URL:-https://github.com/kingsnakerrr/dbonline-media-stack.git}"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }

need_root() {
  if [ "$(id -u)" != "0" ]; then
    red "请用 root 用户运行安装脚本"
    exit 1
  fi
}

rand_pass() {
  openssl rand -base64 24 | tr -dc 'A-Za-z0-9_@#%+=' | cut -c1-20
}

ask() {
  local prompt="$1" default="${2:-}" value
  if [ -n "$default" ]; then
    read -r -p "$prompt [$default]: " value || true
    printf '%s' "${value:-$default}"
  else
    read -r -p "$prompt: " value || true
    printf '%s' "$value"
  fi
}

ask_pass() {
  local prompt="$1" value
  read -r -p "$prompt（留空随机生成）: " value || true
  if [ -z "$value" ]; then
    value="$(rand_pass)"
  fi
  printf '%s' "$value"
}

detect_host() {
  local ip
  ip="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
  if [ -z "$ip" ]; then
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  printf '%s' "${ip:-127.0.0.1}"
}

install_packages() {
  apt-get update
  apt-get install -y ca-certificates curl wget git jq sqlite3 openssl
}

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    return
  fi
  yellow "正在安装 Docker..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
}

install_rclone() {
  if command -v rclone >/dev/null 2>&1; then
    return
  fi
  yellow "正在安装 rclone..."
  curl -fsSL https://rclone.org/install.sh | bash
}

configure_bbr() {
  local enable="$1"
  if [[ ! "$enable" =~ ^[Yy]$ ]]; then
    return
  fi
  cat >/etc/sysctl.d/99-bbr.conf <<'EOF'
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
EOF
  sysctl --system >/dev/null || true
}

configure_swap() {
  local gb="$1"
  if ! [[ "$gb" =~ ^[0-9]+$ ]]; then
    yellow "swap 输入不是数字，跳过"
    return
  fi
  if [ "$gb" = "0" ]; then
    yellow "跳过 swap 设置"
    return
  fi
  yellow "正在清理旧 swap 并设置 ${gb}G swap..."
  swapoff -a || true
  sed -i.bak '/[[:space:]]swap[[:space:]]/d' /etc/fstab
  rm -f /swapfile
  fallocate -l "${gb}G" /swapfile || dd if=/dev/zero of=/swapfile bs=1G count="$gb"
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  printf '/swapfile none swap sw 0 0\n' >>/etc/fstab
}

copy_self_or_clone() {
  mkdir -p "$(dirname "$INSTALL_DIR")"
  if [ -d "$INSTALL_DIR/.git" ]; then
    git -C "$INSTALL_DIR" pull --ff-only
    return
  fi
  if [ -f "./docker-compose.yml" ] && [ -d "./qbittorrent" ] && [ -d "./rclone-manager" ]; then
    mkdir -p "$INSTALL_DIR"
    rsync -a --delete --exclude data --exclude .env ./ "$INSTALL_DIR"/ 2>/dev/null || cp -a ./. "$INSTALL_DIR"/
  else
    if [ -e "$INSTALL_DIR" ]; then
      mv "$INSTALL_DIR" "${INSTALL_DIR}.bak.$(date +%Y%m%d-%H%M%S)"
    fi
    git clone "$REPO_URL" "$INSTALL_DIR"
  fi
}

write_env() {
  local domain="$1" db_user="$2" db_pass="$3" pg_pass="$4" qb_user="$5" qb_pass="$6" mdc_user="$7" mdc_pass="$8" rm_user="$9" rm_pass="${10}" avdb_user="${11}" avdb_pass="${12}" avdb_pg_pass="${13}"
  cat >"$INSTALL_DIR/.env" <<EOF
DOMAIN=$domain
TZ=Asia/Shanghai

DBONLINE_PORT=9090
DBONLINE_USER=$db_user
DBONLINE_PASSWORD=$db_pass
DBONLINE_POSTGRES_PASSWORD=$pg_pass

QBITTORRENT_PORT=8080
QBITTORRENT_BT_PORT=6881
QBITTORRENT_USER=$qb_user
QBITTORRENT_PASSWORD=$qb_pass
QBITTORRENT_DOWNLOAD_DIR=/home/dbonline_downloads

MDCNG_PORT=9208
MDCNG_USER=$mdc_user
MDCNG_PASSWORD=$mdc_pass
MDCNG_WATCH_DIR=/home/dbonline_downloads
MDCNG_OUTPUT_DIR=/home/mdcng_guaxiao

RCLONE_MANAGER_PORT=7071
RCLONE_MANAGER_USER=$rm_user
RCLONE_MANAGER_PASSWORD=$rm_pass
RCLONE_WATCH_DIR=/home/mdcng_guaxiao
RCLONE_MIN_AGE=5m

AVDB_PORT=8000
AVDB_USER=$avdb_user
AVDB_PASSWORD=$avdb_pass
AVDB_POSTGRES_PASSWORD=$avdb_pg_pass

FLARESOLVERR_PORT=8191
EOF
}

prepare_dirs() {
  mkdir -p /home/dbonline_downloads /home/dbonline_downloads/.incomplete /home/mdcng_guaxiao /root/.config/rclone
  mkdir -p "$INSTALL_DIR/data"/{dbonline/data,dbonline/cache,dbonline/logs,dbonline-postgres,qbittorrent,mdcng/config,rclone-manager/data,rclone-manager/logs,avdb,avdb-postgres}
}

install_control_command() {
  ln -sf "$INSTALL_DIR/media" /usr/local/bin/media
}

post_configure() {
  bash "$INSTALL_DIR/scripts/post-configure.sh" || true
}

print_info() {
  local domain="$1" db_user="$2" db_pass="$3" qb_user="$4" qb_pass="$5" mdc_user="$6" mdc_pass="$7" rm_user="$8" rm_pass="$9" avdb_user="${10}" avdb_pass="${11}" pg_pass="${12}" avdb_pg_pass="${13}"
  cat >"$INSTALL_DIR/install-info.txt" <<EOF
dbonline-media-stack 安装信息

DBOnline:
地址: http://$domain:9090
账号: $db_user
密码: $db_pass
默认下载目录: /home/dbonline_downloads

qBittorrent:
地址: http://$domain:8080
账号: $qb_user
密码: $qb_pass
下载目录: /home/dbonline_downloads

MDC-NG:
地址: http://$domain:9208
账号: $mdc_user
密码: $mdc_pass
监控目录: /home/dbonline_downloads
刮削输出: /home/mdcng_guaxiao
FlareSolverr: http://flaresolverr:8191/v1

Rclone Manager:
地址: http://$domain:7071
账号: $rm_user
密码: $rm_pass
监控目录: /home/mdcng_guaxiao
目录稳定时间: 5m

AVDB:
地址: http://$domain:8000
账号: $avdb_user
密码: $avdb_pass
FlareSolverr: http://flaresolverr:8191/v1

FlareSolverr:
地址: http://$domain:8191
容器内地址: http://flaresolverr:8191/v1

rclone:
请把配置文件放到: /root/.config/rclone/rclone.conf
Rclone Manager 会读取这个文件。

数据库密码:
DBOnline PostgreSQL: $pg_pass
AVDB PostgreSQL: $avdb_pg_pass

常用命令:
media status
media logs
media restart
media update
EOF
  cat "$INSTALL_DIR/install-info.txt"
}

main() {
  need_root
  local default_domain domain db_user db_pass pg_pass qb_user qb_pass mdc_user mdc_pass rm_user rm_pass avdb_user avdb_pass avdb_pg_pass swap_gb bbr
  default_domain="$(detect_host)"
  domain="$(ask '请输入访问域名/IP' "$default_domain")"
  db_user="$(ask '请输入 DBOnline 账号' admin)"
  db_pass="$(ask_pass '请输入 DBOnline 密码')"
  qb_user="$(ask '请输入 qBittorrent 账号' admin)"
  qb_pass="$(ask_pass '请输入 qBittorrent 密码')"
  mdc_user="$(ask '请输入 MDC-NG 账号' admin)"
  mdc_pass="$(ask_pass '请输入 MDC-NG 密码')"
  rm_user="$(ask '请输入 Rclone Manager 账号' admin)"
  rm_pass="$(ask_pass '请输入 Rclone Manager 密码')"
  avdb_user="$(ask '请输入 AVDB 账号' admin)"
  avdb_pass="$(ask_pass '请输入 AVDB 密码')"
  pg_pass="$(ask_pass '请输入 DBOnline 数据库密码')"
  avdb_pg_pass="$(ask_pass '请输入 AVDB 数据库密码')"
  swap_gb="$(ask '请输入 swap 大小 GB，0 表示不设置；会清除旧 swap 后重建' 16)"
  bbr="$(ask '是否开启 BBR' Y)"

  install_packages
  install_docker
  install_rclone
  configure_swap "$swap_gb"
  configure_bbr "$bbr"
  copy_self_or_clone
  chmod +x "$INSTALL_DIR/install.sh" "$INSTALL_DIR/media" "$INSTALL_DIR/scripts/"*.sh "$INSTALL_DIR/qbittorrent/entrypoint.sh" || true
  write_env "$domain" "$db_user" "$db_pass" "$pg_pass" "$qb_user" "$qb_pass" "$mdc_user" "$mdc_pass" "$rm_user" "$rm_pass" "$avdb_user" "$avdb_pass" "$avdb_pg_pass"
  prepare_dirs
  install_control_command

  cd "$INSTALL_DIR"
  docker compose up -d --build
  post_configure
  green "安装完成！"
  print_info "$domain" "$db_user" "$db_pass" "$qb_user" "$qb_pass" "$mdc_user" "$mdc_pass" "$rm_user" "$rm_pass" "$avdb_user" "$avdb_pass" "$pg_pass" "$avdb_pg_pass"
}

main "$@"
