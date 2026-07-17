#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/dbonline-media-stack"
cd "$APP_DIR"
set -a
source ./.env
set +a

wait_http() {
  local url="$1" name="$2"
  for i in $(seq 1 90); do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "等待 $name 超时，跳过自动后置配置"
  return 1
}

configure_qb() {
  wait_http "http://127.0.0.1:${QBITTORRENT_PORT}/api/v2/app/version" "qBittorrent" || return 0
  local prefs
  prefs=$(jq -nc \
    --arg user "$QBITTORRENT_USER" \
    --arg pass "$QBITTORRENT_PASSWORD" \
    --arg dir "$QBITTORRENT_DOWNLOAD_DIR" \
    --argjson port "$QBITTORRENT_BT_PORT" \
    '{
      web_ui_username:$user,
      web_ui_password:$pass,
      web_ui_session_timeout:604800,
      bypass_local_auth:true,
      bypass_auth_subnet_whitelist_enabled:true,
      bypass_auth_subnet_whitelist:"127.0.0.1/32,172.16.0.0/12",
      web_ui_host_header_validation_enabled:false,
      web_ui_csrf_protection_enabled:false,
      save_path:($dir + "/"),
      temp_path:($dir + "/.incomplete/"),
      temp_path_enabled:true,
      listen_port:$port,
      up_limit:10485760,
      max_connec:2000,
      max_connec_per_torrent:500,
      max_uploads:200,
      max_uploads_per_torrent:50,
      dht:true,
      pex:true,
      lsd:true,
      queueing_enabled:false
    }')
  curl -fsS -X POST "http://127.0.0.1:${QBITTORRENT_PORT}/api/v2/app/setPreferences" --data-urlencode "json=$prefs" >/dev/null || true
}

configure_dbonline_hint() {
  wait_http "http://127.0.0.1:${DBONLINE_PORT}/api/auth/status" "DBOnline" || return 0
  echo "DBOnline 已启动。若首次进入需要初始化，请使用 install-info.txt 中的密码。"
  echo "qB 容器内地址: qbittorrent:8080，下载目录: /home/dbonline_downloads"
}

seed_rclone_manager_task() {
  # Rclone remote/目标目录需要用户放置 /root/.config/rclone/rclone.conf 后在前端选择，
  # 这里不强行创建任务，避免远程名未知导致误配置。
  mkdir -p /root/.config/rclone
}

configure_qb
configure_dbonline_hint
seed_rclone_manager_task
