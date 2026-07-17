#!/usr/bin/env bash
set -euo pipefail

export HOME=/config
export XDG_CONFIG_HOME=/config/.config
export XDG_DATA_HOME=/config/.local/share

USER_NAME="${QBITTORRENT_USER:-admin}"
USER_PASS="${QBITTORRENT_PASSWORD:-adminadmin}"
DOWNLOAD_DIR="${QBITTORRENT_DOWNLOAD_DIR:-/home/dbonline_downloads}"
BT_PORT="${QBITTORRENT_BT_PORT:-6881}"

CONF_DIR="$XDG_CONFIG_HOME/qBittorrent"
CONF_FILE="$CONF_DIR/qBittorrent.conf"
mkdir -p "$CONF_DIR" "$XDG_DATA_HOME/qBittorrent" "$DOWNLOAD_DIR/.incomplete"

if [ ! -f "$CONF_FILE" ]; then
  cat > "$CONF_FILE" <<EOF
[LegalNotice]
Accepted=true

[Preferences]
Connection\\PortRangeMin=$BT_PORT
Downloads\\SavePath=$DOWNLOAD_DIR/
Downloads\\TempPath=$DOWNLOAD_DIR/.incomplete/
Downloads\\TempPathEnabled=true
WebUI\\Address=*
WebUI\\Port=8080
WebUI\\Username=$USER_NAME
WebUI\\LocalHostAuth=false
WebUI\\AuthSubnetWhitelist=127.0.0.1/32, 172.16.0.0/12
WebUI\\AuthSubnetWhitelistEnabled=true
WebUI\\HostHeaderValidation=false
WebUI\\CSRFProtection=false
WebUI\\ClickjackingProtection=true
WebUI\\SessionTimeout=604800
EOF
fi

/usr/local/bin/qbittorrent-nox &
QBT_PID="$!"

for i in $(seq 1 60); do
  if curl -fsS --max-time 2 http://127.0.0.1:8080/api/v2/app/version >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

PREFS=$(cat <<JSON
{
  "web_ui_username": "$USER_NAME",
  "web_ui_password": "$USER_PASS",
  "web_ui_session_timeout": 604800,
  "bypass_local_auth": true,
  "bypass_auth_subnet_whitelist_enabled": true,
  "bypass_auth_subnet_whitelist": "127.0.0.1/32,172.16.0.0/12",
  "web_ui_host_header_validation_enabled": false,
  "web_ui_csrf_protection_enabled": false,
  "save_path": "$DOWNLOAD_DIR/",
  "temp_path": "$DOWNLOAD_DIR/.incomplete/",
  "temp_path_enabled": true,
  "listen_port": $BT_PORT,
  "up_limit": 10485760,
  "max_connec": 2000,
  "max_connec_per_torrent": 500,
  "max_uploads": 200,
  "max_uploads_per_torrent": 50,
  "dht": true,
  "pex": true,
  "lsd": true,
  "queueing_enabled": false
}
JSON
)
curl -fsS --max-time 10 -X POST http://127.0.0.1:8080/api/v2/app/setPreferences --data-urlencode "json=$PREFS" >/dev/null || true

wait "$QBT_PID"
