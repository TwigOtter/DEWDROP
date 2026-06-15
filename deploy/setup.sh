#!/usr/bin/env bash
# DEWDROP bootstrap — the privileged bits. Run from the staging dir:
#     sudo bash /home/twig/dewdrop/deploy/setup.sh
#
# It creates the `dewdrop` service user, installs the project at /opt/dewdrop,
# builds the venv, initializes the DB, and installs+enables the systemd units.
set -euo pipefail

STAGING="/home/twig/dewdrop"
TARGET="/opt/dewdrop"
SVC_USER="dewdrop"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo." >&2; exit 1
fi

# 1. Service user (system account, no login).
if ! id "$SVC_USER" &>/dev/null; then
  useradd --system --create-home --shell /usr/sbin/nologin "$SVC_USER"
  echo "Created user $SVC_USER"
fi

# 2. Install tree at /opt/dewdrop (preserves your .env if re-running).
mkdir -p "$TARGET"
rsync -a --exclude venv --exclude '.git' "$STAGING"/ "$TARGET"/
mkdir -p "$TARGET/data" "$TARGET/logs"
chown -R "$SVC_USER:$SVC_USER" "$TARGET"
chmod -R g-w,o-rwx "$TARGET"

# 3. Python venv + deps (run as the service user).
if [[ ! -d "$TARGET/venv" ]]; then
  sudo -u "$SVC_USER" python3 -m venv "$TARGET/venv"
fi
sudo -u "$SVC_USER" "$TARGET/venv/bin/pip" install --upgrade pip
# Editable install so `import dewdrop` works no matter the cwd / how the
# scripts are launched (the systemd units run `python scripts/foo.py`).
sudo -u "$SVC_USER" "$TARGET/venv/bin/pip" install -e "$TARGET"

# 4. .env — copy the example on first run; you fill in keys + lat/lon after.
if [[ ! -f "$TARGET/.env" ]]; then
  cp "$TARGET/.env.example" "$TARGET/.env"
  chown "$SVC_USER:$SVC_USER" "$TARGET/.env"
  chmod 600 "$TARGET/.env"
  echo "Created $TARGET/.env — edit it before starting the timers."
fi

# 5. Initialize the SQLite schema.
sudo -u "$SVC_USER" "$TARGET/venv/bin/python" "$TARGET/scripts/init_db.py"

# 6. systemd units.
cp "$TARGET"/deploy/dewdrop-*.service "$TARGET"/deploy/dewdrop-*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dewdrop-poll.timer dewdrop-actuals.timer dewdrop-score.timer
systemctl enable --now dewdrop-aggregate.timer dewdrop-backup.timer
systemctl enable --now dewdrop-api.service

# Station poller only makes sense if GW2000_HOST is set.
if grep -q "^DEWDROP_GW2000_HOST=.\+" "$TARGET/.env" 2>/dev/null; then
  systemctl enable --now dewdrop-station.timer
  echo "Station poller enabled (dewdrop-station.timer)."
else
  echo "Note: dewdrop-station.timer NOT enabled — set DEWDROP_GW2000_HOST in .env, then:"
  echo "  sudo systemctl enable --now dewdrop-station.timer"
fi

echo
echo "DEWDROP installed at $TARGET."
echo "Next: edit $TARGET/.env (lat/lon, ASOS station, EcoWitt keys, API keys), then:"
echo "  sudo systemctl restart dewdrop-api"
echo "  systemctl list-timers 'dewdrop-*'"
