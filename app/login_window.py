"""A normal (titled, resizable, focusable) window used only to sign in to
a Google/YouTube account. It shares the persistent browser profile with the
compact band window, so once you sign in here the band window's embedded
player is signed in too. Opened on demand from the tray menu -- the band
window itself stays small and non-focusable, which is too cramped for a
comfortable login flow."""
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from .browser_profile import get_profile


# Going straight to youtube.com just shows the (mobile) homepage, which
# looks like an already-logged-in page rather than a login screen if a
# session cookie already exists from before -- and gives no obvious way
# to switch accounts. This URL forces the actual Google sign-in form.
LOGIN_URL = (
    "https://accounts.google.com/ServiceLogin"
    "?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2F"
)


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Googleアカウントにログイン - OnGameShorts")
        self.resize(900, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.web_view = QWebEngineView(self)
        # Keep strong Python references (see band_window.py's _init_webview
        # for why this matters -- a GC'd QWebEnginePage crashes the process).
        self._profile = get_profile()
        self._page = QWebEnginePage(self._profile, self.web_view)
        self.web_view.setPage(self._page)
        self.web_view.load(QUrl(LOGIN_URL))

        layout.addWidget(self.web_view)
