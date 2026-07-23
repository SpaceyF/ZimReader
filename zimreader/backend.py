"""wrapper around libzim. opens a zim, pulls entries out, does the suggest + search stuff."""

from __future__ import annotations

from libzim.reader import Archive
from libzim.suggestion import SuggestionSearcher
from libzim.search import Query, Searcher


class ZimBackend:
    def __init__(self) -> None:
        self.archive: Archive | None = None
        self.path: str | None = None

    @property
    def is_open(self) -> bool:
        return self.archive is not None

    def open(self, path: str) -> None:
        self.archive = Archive(path)
        self.path = path

    def title(self) -> str:
        if not self.archive:
            return "ZimReader"
        try:
            return self.archive.get_metadata("Title").decode("utf-8", "replace")
        except (KeyError, RuntimeError):
            return "ZimReader"

    def article_count(self) -> int:
        if not self.archive:
            return 0
        for attr in ("article_count", "all_entry_count", "entry_count"):
            try:
                return int(getattr(self.archive, attr))
            except (AttributeError, TypeError):
                continue
        return 0

    def main_path(self) -> str | None:
        if not self.archive or not self.archive.has_main_entry:
            return None
        entry = self.archive.main_entry
        if entry.is_redirect:
            entry = entry.get_redirect_entry()
        return entry.path

    # --- getting the actual article content ---
    def _variants(self, path: str):
        # some zims stick content under an "A/" prefix and some dont, annoying.
        # so we just try it plain, then with and without the prefix til one works.
        yield path
        if path.startswith("A/"):
            yield path[2:]
        else:
            yield "A/" + path

    def random_article(self) -> tuple[str, str] | None:
        """grab a random article as (path, title). this is what the wikirace runs on."""
        if not self.archive:
            return None
        try:
            entry = self.archive.get_random_entry()
        except (AttributeError, RuntimeError):
            return None
        if entry.is_redirect:
            entry = entry.get_redirect_entry()
        return entry.path, entry.title

    def get_content(self, path: str) -> tuple[bytes, str]:
        if not self.archive:
            raise KeyError(path)
        last_err: Exception | None = None
        for p in self._variants(path):
            try:
                entry = self.archive.get_entry_by_path(p)
                if entry.is_redirect:
                    entry = entry.get_redirect_entry()
                item = entry.get_item()
                return bytes(item.content), item.mimetype
            except KeyError as e:
                last_err = e
        raise last_err or KeyError(path)

    # --- little lookup helpers ---
    def _resolve(self, path: str) -> tuple[str, str] | None:
        """turn a result path into (title, path), or None if it doesnt actually resolve."""
        try:
            entry = self.archive.get_entry_by_path(path)
            return entry.title, path
        except KeyError:
            return None

    def suggest(self, text: str, count: int = 12) -> list[tuple[str, str]]:
        """quick title suggestions for the search box while you type."""
        if not self.archive or not text.strip():
            return []
        searcher = SuggestionSearcher(self.archive)
        suggestion = searcher.suggest(text)
        n = min(count, suggestion.getEstimatedMatches())
        out = []
        for path in suggestion.getResults(0, n):
            r = self._resolve(path)
            if r:
                out.append(r)
        return out

    def search(self, text: str, count: int = 40) -> list[tuple[str, str]]:
        """full text search. if the zim has no fulltext index we just fall back to titles."""
        if not self.archive or not text.strip():
            return []
        if not self.archive.has_fulltext_index:
            return self.suggest(text, count)
        searcher = Searcher(self.archive)
        search = searcher.search(Query().set_query(text))
        n = min(count, search.getEstimatedMatches())
        out = []
        for path in search.getResults(0, n):
            r = self._resolve(path)
            if r:
                out.append(r)
        return out
