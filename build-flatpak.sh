#!/usr/bin/env bash
# builds + installs zimreader as a flatpak on kubuntu/kde. run it and go grab a drink.
#
#   ./build-flatpak.sh            # let it pick a kde runtime version
#   ./build-flatpak.sh 6.8        # or force one yourself
#
set -euo pipefail
cd "$(dirname "$0")"

APP_ID="io.github.SpaceyF.ZimReader"
MANIFEST="$APP_ID.yml"
BUILD_MANIFEST="$APP_ID.build.yml"

say()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ -f "$MANIFEST" ] || die "run this from inside the ZimReader folder (cant find $MANIFEST)."

# 1. make sure the tools we actually need are here
if ! command -v flatpak >/dev/null 2>&1 || ! command -v flatpak-builder >/dev/null 2>&1; then
  say "installing flatpak + flatpak-builder (needs sudo)..."
  sudo apt update
  sudo apt install -y flatpak flatpak-builder
fi

say "making sure flathub is set up properly..."
# the proper repo file comes with the gpg key + summary, a bare url doesnt
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo 2>/dev/null \
  || sudo flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
# if flathubs busted (that "no summary found" thing) just nuke it and re-add, so you dont have to type fix commands
if ! flatpak remote-ls flathub >/dev/null 2>&1; then
  say "flathub had no usable summary, re-adding it clean..."
  sudo flatpak remote-delete --force flathub 2>/dev/null || true
  flatpak --user remote-delete --force flathub 2>/dev/null || true
  sudo flatpak remote-add flathub https://dl.flathub.org/repo/flathub.flatpakrepo
fi
flatpak update --appstream -y >/dev/null 2>&1 || sudo flatpak update --appstream -y >/dev/null 2>&1 || true

# 2. find a version that BOTH the kde platform and the pyside base app actually have
V="${1:-}"
if [ -z "$V" ]; then
  say "figuring out which kde runtime version to use..."
  for cand in 6.9 6.8 6.7 6.6; do
    if flatpak remote-info flathub "org.kde.Platform//$cand"     >/dev/null 2>&1 \
    && flatpak remote-info flathub "io.qt.PySide.BaseApp//$cand" >/dev/null 2>&1; then
      V="$cand"; break
    fi
  done
fi
[ -n "$V" ] || die "couldnt figure out a version. just pass one, like ./build-flatpak.sh 6.8
  (to see what exists:  flatpak remote-ls flathub | grep -E 'org.kde.Platform|PySide.BaseApp')"
say "going with kde runtime / pyside version: $V"

# 3. grab the runtime, sdk and base app
say "grabbing runtime + sdk + pyside base app (big download the first time)..."
flatpak install -y flathub "org.kde.Platform//$V" "org.kde.Sdk//$V" "io.qt.PySide.BaseApp//$V"

# 4. jam that version into a temp copy of the manifest
sed -E "s/^(runtime-version|base-version): .*/\1: '$V'/" "$MANIFEST" > "$BUILD_MANIFEST"
trap 'rm -f "$BUILD_MANIFEST"' EXIT

# 5. actually build it and install it for your user
say "building + installing zimreader... (compiles some pyside bits, give it a few mins)"
flatpak-builder --user --install --force-clean build-dir "$BUILD_MANIFEST"

say "done. launch it with:"
printf '    flatpak run %s\n' "$APP_ID"
printf '  or just find "ZimReader" in your app menu.\n'
