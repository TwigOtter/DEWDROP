#!/usr/bin/env bash
# DEWDROP push — sync code from staging to /opt/dewdrop and restart the API.
# Run after editing /home/twig/dewdrop:
#     sudo bash /home/twig/dewdrop/deploy/push.sh [--no-restart] [--reinstall]
#
# Staging (/home/twig/dewdrop) is the source of truth; this script keeps
# /opt/dewdrop in lockstep with it. State that lives only in production —
# .env, data/, logs/ — is never touched.
set -euo pipefail

STAGING="/home/twig/dewdrop"
TARGET="/opt/dewdrop"
SVC_USER="dewdrop"
RESTART=1
REINSTALL=0
WITH_ENV=0

for arg in "$@"; do
  case "$arg" in
    --no-restart) RESTART=0 ;;
    --reinstall)  REINSTALL=1 ;;
    --with-env)   WITH_ENV=1 ;;
    -h|--help)
      sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo." >&2; exit 1
fi

if [[ ! -d "$TARGET" ]]; then
  echo "$TARGET does not exist — run deploy/setup.sh first." >&2; exit 1
fi

ENV_EXCLUDE=(--exclude='.env')
(( WITH_ENV )) && ENV_EXCLUDE=()

rsync -a --delete \
  --exclude='.git' \
  --exclude='venv' \
  "${ENV_EXCLUDE[@]}" \
  --exclude='data' \
  --exclude='logs' \
  --exclude='*.egg-info' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  "$STAGING"/ "$TARGET"/

# Re-assert the hardened ownership/perms setup.sh originally applied,
# in case rsync brought in anything new.
chown -R "$SVC_USER:$SVC_USER" "$TARGET"
chmod -R g-w,o-rwx "$TARGET"
[[ -f "$TARGET/.env" ]] && chmod 600 "$TARGET/.env"

# systemd loads units from /etc/systemd/system, not /opt/dewdrop/deploy.
# Re-copy any changed unit files and reload so a port/ExecStart edit actually
# takes effect on the next restart.
cp -u "$TARGET"/deploy/dewdrop-*.service "$TARGET"/deploy/dewdrop-*.timer /etc/systemd/system/
systemctl daemon-reload

if (( REINSTALL )); then
  sudo -u "$SVC_USER" "$TARGET/venv/bin/pip" install -e "$TARGET"
fi

if (( RESTART )); then
  systemctl restart dewdrop-api
  echo "Restarted dewdrop-api."
fi

echo "Pushed $STAGING → $TARGET."
