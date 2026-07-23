"""where it all kicks off. register the zim:// scheme, start qt, build the shelf, show the window."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QApplication

from . import APP_ID
from .scheme import register_scheme, ZimSchemeHandler, SCHEME


def main() -> int:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    register_scheme()  # again, this has to happen before QApplication exists

    app = QApplication(sys.argv)
    app.setApplicationName("ZimReader")
    app.setApplicationDisplayName("ZimReader")
    app.setOrganizationName("SpaceyF")
    app.setDesktopFileName(APP_ID)

    from PySide6.QtWebEngineCore import QWebEngineProfile
    from .shelf import Shelf

    shelf = Shelf(QSettings("SpaceyF", "ZimReader"))
    shelf.load()

    handler = ZimSchemeHandler(shelf)
    QWebEngineProfile.defaultProfile().installUrlSchemeHandler(SCHEME, handler)

    from .window import MainWindow
    win = MainWindow(shelf, handler)
    win.show()

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    win.open_initial(args[0] if args else None)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
