#!/bin/sh
# the thing the flatpak actually runs.

# 1) make the apps site-packages importable, whatever python minor version the runtime ships
for d in /app/lib/python3.*/site-packages; do
  [ -d "$d" ] && PYTHONPATH="$d${PYTHONPATH:+:$PYTHONPATH}"
done
export PYTHONPATH

# 2) tell qt where the webengine helper process actually is (pyside looks in the wrong spot in flatpak)
if [ -z "$QTWEBENGINEPROCESS_PATH" ]; then
  for c in \
    /app/lib/python3.*/site-packages/PySide6/Qt/libexec/QtWebEngineProcess \
    /app/lib/libexec/QtWebEngineProcess \
    /usr/lib/x86_64-linux-gnu/libexec/QtWebEngineProcess \
    /usr/libexec/QtWebEngineProcess \
    /usr/lib/qt6/libexec/QtWebEngineProcess; do
    if [ -f "$c" ]; then QTWEBENGINEPROCESS_PATH="$c"; break; fi
  done
  [ -z "$QTWEBENGINEPROCESS_PATH" ] && \
    QTWEBENGINEPROCESS_PATH=$(find /app /usr -name QtWebEngineProcess -type f 2>/dev/null | head -1)
  export QTWEBENGINEPROCESS_PATH
fi

# 3) keep webengine from dying in flatpak: chromiums inner sandbox fights flatpaks sandbox,
#    and gpu/egl compositing crashes in here. kill both and render in software.
: "${QTWEBENGINE_DISABLE_SANDBOX:=1}"
export QTWEBENGINE_DISABLE_SANDBOX
case " ${QTWEBENGINE_CHROMIUM_FLAGS:-} " in
  *" --disable-gpu "*) ;;
  *) QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu ${QTWEBENGINE_CHROMIUM_FLAGS:-}" ;;
esac
export QTWEBENGINE_CHROMIUM_FLAGS

exec python3 -m zimreader "$@"
