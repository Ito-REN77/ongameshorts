"""A normal (titled, resizable, focusable) window that shows the same
Shorts video the band window is currently playing. The band window can
never take keyboard focus by design (so it doesn't interrupt whatever
game/app you're using), which means it also can never receive typed
input -- so things like posting a comment, or a login prompt that pops up
mid-interaction, just get stuck there with no way to type into them. This
window shares the persistent browser profile, so it's already signed in,
and gives a normal place to type."""
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from .browser_profile import get_profile


class InteractWindow(QWidget):
    def __init__(self, url):
        super().__init__()
        self.setWindowTitle("OnGameShorts - 拡大表示")
        self.resize(420, 820)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.web_view = QWebEngineView(self)
        # Keep strong Python references (see band_window.py's _init_webview
        # for why this matters -- a GC'd QWebEnginePage crashes the process).
        self._profile = get_profile()
        self._page = QWebEnginePage(self._profile, self.web_view)
        self.web_view.setPage(self._page)
        self.web_view.load(QUrl(url))

        layout.addWidget(self.web_view)
