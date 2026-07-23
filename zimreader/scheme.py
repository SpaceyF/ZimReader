"""the ``zim://<id>/<path>`` url scheme. the host bit picks which zim on the shelf to read
from, so webengine can pull articles/images/css straight out of whichever zim is open."""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QUrl
from PySide6.QtWebEngineCore import (
    QWebEngineUrlScheme,
    QWebEngineUrlSchemeHandler,
    QWebEngineUrlRequestJob,
)

SCHEME = b"zim"


def register_scheme() -> None:
    """heads up: gotta call this BEFORE the QApplication exists or it wont take."""
    scheme = QWebEngineUrlScheme(SCHEME)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(
        QWebEngineUrlScheme.Flag.SecureScheme
        | QWebEngineUrlScheme.Flag.LocalAccessAllowed
        | QWebEngineUrlScheme.Flag.CorsEnabled
        | QWebEngineUrlScheme.Flag.ContentSecurityPolicyIgnored
    )
    QWebEngineUrlScheme.registerScheme(scheme)


def to_url(zim_id: str, path: str) -> QUrl:
    url = QUrl()
    url.setScheme("zim")
    url.setHost(zim_id)
    url.setPath("/" + path.lstrip("/"))
    return url


class ZimSchemeHandler(QWebEngineUrlSchemeHandler):
    def __init__(self, shelf, parent=None) -> None:
        super().__init__(parent)
        self.shelf = shelf

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:
        url = job.requestUrl()
        backend = self.shelf.backend(url.host())
        if backend is None:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        path = url.path()
        if path.startswith("/"):
            path = path[1:]
        path = QUrl.fromPercentEncoding(path.encode("utf-8"))
        try:
            content, mime = backend.get_content(path)
        except KeyError:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        buf = QBuffer(job)
        buf.setData(QByteArray(content))
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(QByteArray(mime.encode("ascii", "replace")), buf)
