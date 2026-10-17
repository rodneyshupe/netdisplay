#!/usr/bin/env bash
# Install netdisplay on a Debian/Raspberry Pi OS box.
#
#   sudo ./install.sh [--config FILE] [--no-lcd] [--no-web]
#   sudo ./install.sh --uninstall
#
# --config FILE  config to install as /etc/netdisplay/config.yaml (never overwrites an existing one;
#                default: examples/basic.yaml)
# --no-lcd       don't install/enable the LCD service
# --no-web       don't install/enable the web service
set -euo pipefail
cd "$(dirname "$0")"

LCD=1; WEB=1; CONFIG=""; UNINSTALL=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config) CONFIG="$2"; shift 2 ;;
        --no-lcd) LCD=0; shift ;;
        --no-web) WEB=0; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }

if [[ $UNINSTALL -eq 1 ]]; then
    systemctl disable --now netdisplay.service netdisplay-web.service 2>/dev/null || true
    rm -f /etc/systemd/system/netdisplay.service /etc/systemd/system/netdisplay-web.service /usr/local/bin/netdisplay
    rm -rf /opt/netdisplay
    systemctl daemon-reload
    echo "removed (left /etc/netdisplay/config.yaml in place)"
    exit 0
fi

echo "== packages"
apt-get update -qq
apt-get install -y python3-yaml python3-pil fonts-dejavu-core

echo "== files"
rm -rf /opt/netdisplay
install -d /opt/netdisplay
cp -r netdisplay /opt/netdisplay/netdisplay
find /opt/netdisplay -name __pycache__ -prune -exec rm -rf {} +
rm -f /usr/local/bin/netdisplay      # may be a symlink from an older install
cat > /usr/local/bin/netdisplay <<'WRAP'
#!/bin/sh
PYTHONPATH=/opt/netdisplay exec python3 -m netdisplay "$@"
WRAP
chmod 755 /usr/local/bin/netdisplay

install -d /etc/netdisplay
if [[ ! -e /etc/netdisplay/config.yaml ]]; then
    install -m 644 "${CONFIG:-examples/basic.yaml}" /etc/netdisplay/config.yaml
    echo "installed ${CONFIG:-examples/basic.yaml} as /etc/netdisplay/config.yaml: edit it, then 'netdisplay validate'"
elif [[ -n "$CONFIG" ]]; then
    echo "kept existing /etc/netdisplay/config.yaml (ignoring --config); compare with: diff $CONFIG /etc/netdisplay/config.yaml"
fi

echo "== services"
install -m 644 systemd/netdisplay.service systemd/netdisplay-web.service /etc/systemd/system/
systemctl daemon-reload
[[ $LCD -eq 1 ]] && systemctl enable netdisplay.service && systemctl restart netdisplay.service
[[ $WEB -eq 1 ]] && systemctl enable netdisplay-web.service && systemctl restart netdisplay-web.service
sleep 2
systemctl --no-pager status netdisplay.service netdisplay-web.service 2>/dev/null | grep -E '●|Active' || true

echo "== validate"
netdisplay validate || echo "(fix the problems above, then: sudo systemctl restart netdisplay netdisplay-web)"
