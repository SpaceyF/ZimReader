#!/usr/bin/env bash
# gets qtwebengine working in the zimreader flatpak, then launches it. safe to re-run.
#   bash fix-webengine.sh
APP=io.github.SpaceyF.ZimReader

echo "hunting down QtWebEngineProcess..."
P=$(flatpak run --command=sh "$APP" -c 'find /app /usr -name QtWebEngineProcess -type f 2>/dev/null | head -1' || true)
if [ -n "$P" ]; then
  echo "found it: $P"
  flatpak override --user --env=QTWEBENGINEPROCESS_PATH="$P" "$APP"
fi

# chromiums own sandbox fights with flatpaks sandbox, so turn it off
flatpak override --user --env=QTWEBENGINE_DISABLE_SANDBOX=1 "$APP"

# gpu/egl compositing dies inside the sandbox (eglCreateImage, context-lost), so just render in software
flatpak override --user --env=QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu "$APP"

echo
echo "launching (if it crashes, the reason shows up below)..."
echo "----------------------------------------------------"
flatpak run "$APP"
