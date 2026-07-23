"""the shelf. basically a bunch of open zims, each with its own stable id.

that id is also the ``zim://<id>/<path>`` url host, which is the trick that lets you have
articles from different zims open at the same time (in tabs) without their relative links
stepping on each other. each zim resolves its own links.
"""

from __future__ import annotations

import hashlib
import os
import re

from .backend import ZimBackend


def make_id(path: str) -> str:
    base = os.path.splitext(os.path.basename(path))[0].lower()
    slug = re.sub(r"[^a-z0-9]+", "-", base).strip("-") or "zim"
    h = hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:6]
    return f"{slug}-{h}"  # url-safe, unique per file, and still readable so i can debug it


class Shelf:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.backends: dict[str, ZimBackend] = {}
        self.paths: dict[str, str] = {}

    def load(self) -> None:
        stored = self.settings.value("shelf", [], type=list) or []
        for p in stored:
            if isinstance(p, str) and os.path.exists(p):
                try:
                    self.add(p, persist=False)
                except Exception:  # noqa: BLE001 - if a zim wont open just skip it, no crash
                    pass

    def _persist(self) -> None:
        self.settings.setValue("shelf", list(self.paths.values()))

    def add(self, path: str, persist: bool = True) -> str:
        path = os.path.abspath(path)
        zid = make_id(path)
        if zid not in self.backends:
            backend = ZimBackend()
            backend.open(path)
            self.backends[zid] = backend
            self.paths[zid] = path
            if persist:
                self._persist()
        return zid

    def remove(self, zid: str) -> None:
        self.backends.pop(zid, None)
        self.paths.pop(zid, None)
        self._persist()

    def backend(self, zid: str) -> ZimBackend | None:
        return self.backends.get(zid)

    def title_of(self, zid: str) -> str:
        b = self.backends.get(zid)
        return b.title() if b else zid

    def entries(self) -> list[tuple[str, str, str, int]]:
        """spits out (id, path, title, article_count) for each zim, sorted by title."""
        out = [(zid, self.paths[zid], b.title(), b.article_count())
               for zid, b in self.backends.items()]
        return sorted(out, key=lambda e: e[2].lower())

    @property
    def is_empty(self) -> bool:
        return not self.backends
