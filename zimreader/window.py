"""the main window. tabs, the zim shelf, search, find-in-page, all themed to match kde."""

from __future__ import annotations

import html
import os
import time

from PySide6.QtCore import Qt, QTimer, QStringListModel, QSettings, QEvent
from PySide6.QtGui import QAction, QKeySequence, QPalette, QGuiApplication, QColor
from PySide6.QtWidgets import (
    QMainWindow, QToolBar, QLineEdit, QCompleter, QFileDialog, QMessageBox,
    QWidget, QSizePolicy, QStyle, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QToolButton, QTabWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile

from .scheme import to_url

# lazy but bulletproof dark mode. flip the whole page, then un-flip images/video so photos still look right.
_DARK_JS = """
(function(dark){
  var id='__zimreader_dark__';
  var el=document.getElementById(id);
  if(dark){
    if(!el){el=document.createElement('style');el.id=id;(document.head||document.documentElement).appendChild(el);}
    el.textContent='html{filter:invert(1) hue-rotate(180deg) !important;background:#e6e6e6 !important;}'+
      'img,video,canvas,svg,picture,[style*="url("],.mwe-math-fallback-image-inline,.thumbimage{filter:invert(1) hue-rotate(180deg) !important;}';
  } else if(el){ el.remove(); }
})(%s);
"""


class TabPage(QWebEnginePage):
    """a page that turns "open in new window" (middle click, ctrl click, target=_blank) into a new tab."""

    def __init__(self, win: "MainWindow") -> None:
        super().__init__(QWebEngineProfile.defaultProfile(), win)
        self._win = win

    def createWindow(self, wtype):
        bg = wtype == QWebEnginePage.WebWindowType.WebBrowserBackgroundTab
        view = self._win.new_tab(select=not bg, blank=True)
        return view.page()


class MainWindow(QMainWindow):
    def __init__(self, shelf, handler) -> None:
        super().__init__()
        self.shelf = shelf
        self.handler = handler
        self.settings = QSettings("SpaceyF", "ZimReader")
        self._sugg_map: dict[str, tuple[str, str]] = {}  # what you see in the dropdown -> (zim_id, path)

        self.resize(1150, 780)
        self.setWindowTitle("ZimReader")

        # tabs
        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # stack em up: race bar on top, tabs in the middle, find bar hiding at the bottom
        central = QWidget(self)
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self._build_race_bar()
        col.addWidget(self.race_bar)
        self.race_bar.hide()
        col.addWidget(self.tabs, 1)
        self._build_find_bar()
        col.addWidget(self.find_bar)
        self.find_bar.hide()
        self.setCentralWidget(central)

        self._build_toolbar()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._update_suggestions)

        # wikirace stuff. the timer just keeps that little clock in the hud ticking
        self._race: dict | None = None
        self._race_timer = QTimer(self)
        self._race_timer.setInterval(500)
        self._race_timer.timeout.connect(self._update_race_hud)

        self.new_tab(blank=True)  # open with one empty tab, open_initial fills it in a sec

    # ---------------- tabs ----------------
    def _new_view(self) -> QWebEngineView:
        view = QWebEngineView(self)
        view.setPage(TabPage(self))
        view._zim_id = None  # type: ignore[attr-defined]
        view.loadFinished.connect(lambda ok, v=view: self._on_view_load(v, ok))
        view.urlChanged.connect(lambda u, v=view: self._on_view_url(v, u))
        view.titleChanged.connect(lambda t, v=view: self._on_view_title(v, t))
        self._apply_view_background(view)
        return view

    def new_tab(self, url=None, select: bool = True, blank: bool = False) -> QWebEngineView:
        view = self._new_view()
        idx = self.tabs.addTab(view, "New Tab")
        if select:
            self.tabs.setCurrentIndex(idx)
        if not blank:
            if url is not None:
                view.setUrl(url)
            else:
                self.show_shelf(view)
        return view

    def current_view(self) -> QWebEngineView | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, QWebEngineView) else None

    def _close_tab(self, index: int) -> None:
        if self.tabs.count() <= 1:
            self.show_shelf(self.tabs.widget(0))  # if its the last tab dont kill it, just bounce it to the shelf
            return
        w = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if w:
            w.deleteLater()

    def _on_tab_changed(self, _idx: int) -> None:
        self._sync_nav()
        v = self.current_view()
        self._update_title(v.title() if v else "")

    def _on_view_load(self, view: QWebEngineView, ok: bool) -> None:
        if ok:
            self._apply_dark(view)

    def _on_view_url(self, view: QWebEngineView, url) -> None:
        host = url.host()
        view._zim_id = host if host in self.shelf.backends else None  # type: ignore[attr-defined]
        if view is self.current_view():
            self._sync_nav()
        self._race_progress(view, url)

    def _on_view_title(self, view: QWebEngineView, title: str) -> None:
        idx = self.tabs.indexOf(view)
        if idx >= 0:
            self.tabs.setTabText(idx, _elide(title or "New Tab"))
            self.tabs.setTabToolTip(idx, title)
        if view is self.current_view():
            self._update_title(title)

    # ---------------- toolbar ----------------
    def _build_toolbar(self) -> None:
        tb = QToolBar("Main", self)
        tb.setMovable(False)
        self.addToolBar(tb)
        st = self.style()

        self.act_back = _action(self, st, QStyle.StandardPixmap.SP_ArrowBack, "Back",
                                QKeySequence.StandardKey.Back, lambda: self._nav("back"))
        self.act_fwd = _action(self, st, QStyle.StandardPixmap.SP_ArrowForward, "Forward",
                               QKeySequence.StandardKey.Forward, lambda: self._nav("forward"))
        tb.addAction(self.act_back)
        tb.addAction(self.act_fwd)
        tb.addAction(_action(self, st, QStyle.StandardPixmap.SP_DirHomeIcon, "Shelf",
                             QKeySequence("Alt+Home"), lambda: self.show_shelf()))
        tb.addAction(_action(self, st, QStyle.StandardPixmap.SP_DialogOpenButton, "Add ZIM…",
                             QKeySequence.StandardKey.Open, self.open_dialog))
        tb.addAction(_action(self, st, QStyle.StandardPixmap.SP_FileDialogNewFolder, "New tab",
                             QKeySequence.StandardKey.AddTab, lambda: self.new_tab()))
        tb.addSeparator()

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search articles…   (Enter for full-text)")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(360)
        self.search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.search.textEdited.connect(lambda _t: self._debounce.start())
        self.search.returnPressed.connect(self._on_return)

        self.completer = QCompleter(self)
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer_model = QStringListModel(self)
        self.completer.setModel(self._completer_model)
        self.completer.activated[str].connect(self._on_pick)
        self.search.setCompleter(self.completer)
        tb.addWidget(self.search)

        race_btn = QToolButton(self)
        race_btn.setText("🏁 Race")
        race_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        race_btn.setToolTip("Wikirace: reach a random target article using only in-article links")
        race_btn.clicked.connect(self.start_race)
        tb.addWidget(race_btn)

        for seq, slot in (("Ctrl+K", self._focus_search), ("Ctrl+L", self._focus_search),
                          ("Ctrl+W", lambda: self._close_tab(self.tabs.currentIndex()))):
            a = QAction(self)
            a.setShortcut(QKeySequence(seq))
            a.triggered.connect(slot)
            self.addAction(a)

        # find in page
        self.addAction(_bare(self, QKeySequence.StandardKey.Find, self.show_find))
        self.addAction(_bare(self, QKeySequence.StandardKey.FindNext, lambda: self._find(True)))
        self.addAction(_bare(self, QKeySequence.StandardKey.FindPrevious, lambda: self._find(False)))

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _nav(self, which: str) -> None:
        v = self.current_view()
        if v:
            v.back() if which == "back" else v.forward()

    def _sync_nav(self) -> None:
        v = self.current_view()
        h = v.history() if v else None
        self.act_back.setEnabled(bool(h and h.canGoBack()))
        self.act_fwd.setEnabled(bool(h and h.canGoForward()))

    def _update_title(self, title: str) -> None:
        self.setWindowTitle(f"{title} - ZimReader" if title else "ZimReader")

    # ---------------- search ----------------
    def _active_backend(self):
        v = self.current_view()
        zid = getattr(v, "_zim_id", None) if v else None
        return zid, (self.shelf.backend(zid) if zid else None)

    def _update_suggestions(self) -> None:
        text = self.search.text().strip()
        if len(text) < 2 or self.shelf.is_empty:
            self._completer_model.setStringList([])
            return
        zid, backend = self._active_backend()
        results: list[tuple[str, str, str]] = []
        if backend:  # if youre reading an article, just search that zim
            for title, path in backend.suggest(text, 12):
                results.append((title, zid, path))
        else:        # if youre on the shelf page, search everything youve got
            for ezid, be in self.shelf.backends.items():
                for title, path in be.suggest(text, 6):
                    results.append((f"{title}  ·  {self.shelf.title_of(ezid)}", ezid, path))
        self._sugg_map = {d: (z, p) for d, z, p in results}
        self._completer_model.setStringList([d for d, _, _ in results])
        self.completer.complete()

    def _on_pick(self, display: str) -> None:
        hit = self._sugg_map.get(display)
        if hit:
            self.load(*hit)

    def _on_return(self) -> None:
        text = self.search.text().strip()
        if not text:
            return
        if text in self._sugg_map:
            self.load(*self._sugg_map[text])
        else:
            self.show_search_results(text)

    def load(self, zim_id: str, path: str) -> None:
        v = self.current_view() or self.new_tab(blank=True)
        v.setUrl(to_url(zim_id, path))

    # ---------------- generated pages ----------------
    def show_shelf(self, view: QWebEngineView | None = None) -> None:
        view = view or self.current_view()
        if view is None:
            return
        entries = self.shelf.entries()
        if entries:
            rows = "".join(
                f"<li><a href='{to_url(zid, self.shelf.backend(zid).main_path() or '').toString()}'>"
                f"{html.escape(title)}</a> <span class='dim'>· {count:,} articles</span></li>"
                for zid, path, title, count in entries
            )
            body = (f"<div class='wrap'><h1>Your ZIM shelf</h1><ul class='results'>{rows}</ul>"
                    "<p class='dim'>Add more with Ctrl+O · search the whole shelf from the box above.</p></div>")
        else:
            body = ("<div class='wrap'><h1>Your shelf is empty</h1>"
                    "<p>Add a <code>.zim</code> file with <b>Ctrl+O</b>.</p>"
                    "<p class='dim'>Get them from download.kiwix.org.</p></div>")
        view.setHtml(self._page(body, "Shelf"), to_url("shelf", ""))

    def show_search_results(self, query: str) -> None:
        zid, backend = self._active_backend()
        rows: list[tuple[str, str, str]] = []
        if backend:
            rows = [(t, zid, p) for t, p in backend.search(query, 40)]
            scope = self.shelf.title_of(zid)
        else:
            for ezid, be in self.shelf.backends.items():
                rows += [(t, ezid, p) for t, p in be.search(query, 15)]
            scope = "the shelf"
        if rows:
            items = "".join(
                f"<li><a href='{to_url(z, p).toString()}'>{html.escape(t)}</a>"
                + (f" <span class='dim'>· {html.escape(self.shelf.title_of(z))}</span>" if not backend else "")
                + "</li>"
                for t, z, p in rows
            )
            body = (f"<div class='wrap'><h1>Results for “{html.escape(query)}”</h1>"
                    f"<p class='dim'>in {html.escape(scope)}</p><ul class='results'>{items}</ul></div>")
        else:
            body = (f"<div class='wrap'><h1>No results for “{html.escape(query)}”</h1>"
                    "<p class='dim'>Try different words.</p></div>")
        v = self.current_view() or self.new_tab(blank=True)
        v.setHtml(self._page(body, f"Search: {query}"), to_url("shelf", ""))

    def _page(self, body: str, title: str) -> str:
        pal = self.palette()
        bg = pal.color(QPalette.ColorRole.Window).name()
        fg = pal.color(QPalette.ColorRole.WindowText).name()
        link = pal.color(QPalette.ColorRole.Link).name()
        card = pal.color(QPalette.ColorRole.Base).name()
        return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{html.escape(title)}</title><style>
  html,body{{margin:0;height:100%;background:{bg};color:{fg};
    font-family:'Noto Sans','Segoe UI',sans-serif;}}
  .wrap{{max-width:780px;margin:0 auto;padding:44px 28px;}}
  h1{{font-weight:600;}} a{{color:{link};text-decoration:none;}} a:hover{{text-decoration:underline;}}
  code{{background:{card};padding:2px 6px;border-radius:5px;}} .dim{{opacity:.62;}}
  ul.results{{line-height:2;font-size:1.05em;list-style:none;padding:0;}}
  ul.results li{{border-bottom:1px solid {card};padding:6px 2px;}}
</style></head><body>{body}</body></html>"""

    # ---------------- open ----------------
    def open_dialog(self) -> None:
        start = self.settings.value("last_dir", "")
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add ZIM files", start, "ZIM files (*.zim *.zimaa);;All files (*)")
        if not paths:
            return
        for p in paths:
            try:
                self.shelf.add(p)
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "Could not open ZIM", f"{p}\n\n{e}")
        self.settings.setValue("last_dir", os.path.dirname(paths[-1]))
        self.show_shelf()

    def open_path(self, path: str) -> None:
        try:
            zid = self.shelf.add(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Could not open ZIM", f"{path}\n\n{e}")
            return
        mp = self.shelf.backend(zid).main_path()
        if mp:
            self.load(zid, mp)
        else:
            self.show_shelf()

    def open_initial(self, path: str | None) -> None:
        if path:
            self.open_path(path)
        else:
            self.show_shelf()

    # ---------------- wikirace ----------------
    def _build_race_bar(self) -> None:
        bar = QFrame(self)
        bar.setFrameShape(QFrame.Shape.StyledPanel)
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 5, 10, 5)
        self.race_target = QLabel("", bar)
        self.race_target.setTextFormat(Qt.TextFormat.RichText)
        self.race_clicks = QLabel("", bar)
        self.race_time = QLabel("", bar)
        give = QToolButton(bar)
        give.setText("Give up")
        give.setAutoRaise(True)
        give.clicked.connect(lambda: self._end_race(False))
        h.addWidget(self.race_target, 1)
        h.addWidget(self.race_clicks)
        h.addSpacing(14)
        h.addWidget(self.race_time)
        h.addSpacing(14)
        h.addWidget(give)
        self.race_bar = bar

    def start_race(self) -> None:
        zid, backend = self._active_backend()
        if backend is None:
            if self.shelf.is_empty:
                QMessageBox.information(self, "Wikirace", "Add a ZIM to your shelf first (Ctrl+O).")
                return
            zid = next(iter(self.shelf.backends))
            backend = self.shelf.backend(zid)

        start = backend.random_article()
        target = backend.random_article()
        for _ in range(5):  # dont let start and target be the same article, that'd be a boring race
            if start and target and start[0] != target[0]:
                break
            target = backend.random_article()
        if not start or not target or start[0] == target[0]:
            QMessageBox.information(self, "Wikirace", "This ZIM doesn't support random articles to race on.")
            return

        view = self.current_view() or self.new_tab(blank=True)
        self._race = {
            "view": view, "zim_id": zid,
            "target_path": target[0], "target_title": target[1],
            "clicks": 0, "started": False, "t0": time.monotonic(),
        }
        self.search.setEnabled(False)
        self._update_race_hud()
        self.race_bar.show()
        self._race_timer.start()
        view.setUrl(to_url(zid, start[0]))

    def _update_race_hud(self) -> None:
        r = self._race
        if not r:
            return
        self.race_target.setText(f"🏁 Reach: <b>{html.escape(r['target_title'])}</b>")
        self.race_clicks.setText(f"Clicks: {r['clicks']}")
        el = int(time.monotonic() - r["t0"])
        self.race_time.setText(f"{el // 60:02d}:{el % 60:02d}")

    def _race_progress(self, view, url) -> None:
        r = self._race
        if not r or view is not r["view"] or url.host() != r["zim_id"]:
            return
        path = url.path()
        if path.startswith("/"):
            path = path[1:]
        if not path:
            return
        if not r["started"]:
            r["started"] = True  # first hit is just us dropping you on the start article, doesnt count
            return
        r["clicks"] += 1
        self._update_race_hud()
        if _same_article(path, r["target_path"]):
            self._end_race(True)

    def _end_race(self, win: bool) -> None:
        r = self._race
        self._race = None
        self._race_timer.stop()
        self.race_bar.hide()
        self.search.setEnabled(True)
        if not r or not win:
            return
        el = int(time.monotonic() - r["t0"])
        tstr = f"{el // 60:02d}:{el % 60:02d}"
        best = self.settings.value("race_best_clicks", 0, type=int)
        note = ""
        if best == 0 or r["clicks"] < best:
            self.settings.setValue("race_best_clicks", r["clicks"])
            note = "<p class='dim'>New personal best!</p>"
        elif best:
            note = f"<p class='dim'>Your best is {best} clicks.</p>"
        body = (f"<div class='wrap'><h1>🏁 You made it!</h1>"
                f"<p>Reached <b>{html.escape(r['target_title'])}</b> in "
                f"<b>{r['clicks']}</b> click{'s' if r['clicks'] != 1 else ''} and <b>{tstr}</b>.</p>"
                f"{note}<p class='dim'>Hit 🏁 Race for another.</p></div>")
        r["view"].setHtml(self._page(body, "Wikirace"), to_url("shelf", ""))

    # ---------------- find in page ----------------
    def _build_find_bar(self) -> None:
        bar = QFrame(self)
        bar.setFrameShape(QFrame.Shape.StyledPanel)
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 4, 8, 4)
        self.find_edit = QLineEdit(bar)
        self.find_edit.setPlaceholderText("Find in page…")
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.textEdited.connect(lambda _t: self._find(True))
        self.find_edit.installEventFilter(self)
        self.find_count = QLabel("", bar)
        self.find_count.setMinimumWidth(64)

        def tool(text, tip, slot):
            b = QToolButton(bar)
            b.setText(text)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(slot)
            return b

        h.addWidget(QLabel("Find:", bar))
        h.addWidget(self.find_edit, 1)
        h.addWidget(self.find_count)
        h.addWidget(tool("▲", "Previous (Shift+Enter)", lambda: self._find(False)))
        h.addWidget(tool("▼", "Next (Enter)", lambda: self._find(True)))
        h.addWidget(tool("✕", "Close (Esc)", self._hide_find))
        self.find_bar = bar

    def show_find(self) -> None:
        self.find_bar.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        if self.find_edit.text():
            self._find(True)

    def _hide_find(self) -> None:
        self.find_bar.hide()
        v = self.current_view()
        if v:
            v.page().findText("")
            v.setFocus()

    def _find(self, forward: bool) -> None:
        v = self.current_view()
        if not v:
            return
        text = self.find_edit.text()
        if not text:
            self.find_count.setText("")
            v.page().findText("")
            return
        flags = QWebEnginePage.FindFlag(0) if forward else QWebEnginePage.FindFlag.FindBackward

        def on_result(result):
            n = result.numberOfMatches()
            self.find_count.setText(f"{result.activeMatch()}/{n}" if n else "no matches")

        v.page().findText(text, flags, on_result)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.find_edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self._hide_find()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                back = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                self._find(not back)
                return True
        return super().eventFilter(obj, event)

    # ---------------- theming ----------------
    def _is_dark(self) -> bool:
        try:
            return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        except Exception:  # noqa: BLE001
            return self.palette().color(QPalette.ColorRole.Window).lightness() < 128

    def _apply_view_background(self, view: QWebEngineView) -> None:
        col = self.palette().color(QPalette.ColorRole.Window) if self._is_dark() else QColor("white")
        view.page().setBackgroundColor(col)

    def _apply_dark(self, view: QWebEngineView) -> None:
        view.page().runJavaScript(_DARK_JS % ("true" if self._is_dark() else "false"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in (QEvent.Type.ApplicationPaletteChange, QEvent.Type.PaletteChange):
            for i in range(self.tabs.count()):
                v = self.tabs.widget(i)
                if isinstance(v, QWebEngineView):
                    self._apply_view_background(v)
                    self._apply_dark(v)
        super().changeEvent(event)


def _elide(s: str, n: int = 22) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _same_article(a: str, b: str) -> bool:
    norm = lambda x: x[2:] if x.startswith("A/") else x  # noqa: E731
    return norm(a) == norm(b)


def _action(win, st, pixmap, text, shortcut, slot) -> QAction:
    a = QAction(st.standardIcon(pixmap), text, win)
    if shortcut:
        a.setShortcut(shortcut)
    a.triggered.connect(slot)
    return a


def _bare(win, shortcut, slot) -> QAction:
    a = QAction(win)
    a.setShortcut(shortcut)
    a.triggered.connect(slot)
    return a
