"""Entry point: a taskbar-resident YouTube Shorts band player.

Docks a slim always-on-top bar above the taskbar and plays your signed-in
YouTube Shorts recommendations, controllable via global hotkeys without
ever stealing focus from whatever application you're using -- games,
browsers, editors, anything.

Keyboard control uses only RegisterHotKey (no low-level keyboard hooks).
"""
import os
import re
import sys

# Must be set before QApplication is constructed.
#
# - autoplay-policy: lets the embedded player start without a user gesture.
# - the rest: this window never takes OS focus by design (so it doesn't
#   interrupt whatever game/app you're using), but that means Chromium's
#   own renderer-backgrounding/occlusion logic treats it like an inactive
#   background tab and throttles it -- independent of anything our page
#   JS does (a JS-level document.hasFocus() override can't stop this,
#   since it happens below the page). Without these flags, playback would
#   get periodically throttled and stutter/re-pause on its own.
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--autoplay-policy=no-user-gesture-required "
    "--disable-backgrounding-occluded-windows "
    "--disable-renderer-backgrounding "
    "--disable-background-timer-throttling "
    "--disable-features=CalculateNativeWinOcclusion",
)

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
from PyQt6.QtGui import QIcon, QPixmap, QColor, QAction

from app.config import Config
from app.band_window import BandWindow
from app.login_window import LoginWindow
from app.interact_window import InteractWindow
from app.settings_dialog import SettingsDialog
from app.hotkeys import force_foreground


def make_tray_icon():
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor(30, 144, 255))
    return QIcon(pixmap)


_SHORTS_ID_RE = re.compile(r"/shorts/([A-Za-z0-9_-]+)")


def _desktop_shorts_url(band_window_url):
    """The band window deliberately runs YouTube's *mobile* site (see
    browser_profile.py) since it's what actually fits the small band --
    but the mobile Shorts comment panel doesn't render a working comment
    box in this embedded context (no <textarea>/contenteditable shows up
    even after opening it). ?app=desktop makes YouTube serve the real
    www.youtube.com desktop experience instead of redirecting to
    m.youtube.com, even with our mobile UA still in place -- and the
    desktop comment box is the standard, long-stable one that just works.
    Only used for the InteractWindow, which is a normal-sized window
    anyway and doesn't need the mobile layout."""
    match = _SHORTS_ID_RE.search(band_window_url or "")
    video_id = match.group(1) if match else ""
    if video_id:
        return f"https://www.youtube.com/shorts/{video_id}?app=desktop"
    return "https://www.youtube.com/shorts?app=desktop"


def main():
    config = Config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"))

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = BandWindow(config)
    window.show()

    state = {"login_window": None, "interact_window": None, "settings_dialog": None}

    def open_login():
        login = state["login_window"]
        if login is None or not login.isVisible():
            login = LoginWindow()
            login.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            # Once they're done with the login window (closed it, whether
            # or not they actually signed in), refresh the band window so
            # a successful login shows up immediately instead of waiting
            # for a manual "再読み込み".
            login.destroyed.connect(window.reload_current)
            # WA_DeleteOnClose means the underlying C++ object is gone by
            # the time this fires -- clear the stale reference too, or the
            # next open_login() call dereferences a deleted QWidget
            # (RuntimeError: wrapped C/C++ object ... has been deleted).
            login.destroyed.connect(lambda: state.update(login_window=None))
            state["login_window"] = login
            login.show()
        login.raise_()
        login.activateWindow()
        force_foreground(login)
        # SetForegroundWindow (inside force_foreground) only makes the
        # top-level window the OS-active one -- it doesn't hand keyboard
        # focus to a specific *child* widget, and QWebEngineView has its
        # own internal native surface that needs Qt's setFocus() pointed
        # at it explicitly, or typing goes nowhere even though the window
        # looks active. Called both now and once more shortly after,
        # since activation can finish a beat after this line runs.
        login.web_view.setFocus()
        QTimer.singleShot(150, login.web_view.setFocus)

    def open_interact_window():
        def on_url(url):
            existing = state["interact_window"]
            if existing is not None:
                existing.close()
            interact = InteractWindow(_desktop_shorts_url(url))
            state["interact_window"] = interact
            interact.show()
            interact.raise_()
            interact.activateWindow()
            force_foreground(interact)
            interact.web_view.setFocus()
            QTimer.singleShot(150, interact.web_view.setFocus)

        window.get_current_url(on_url)

    def open_settings(start_section="使い方"):
        # Non-modal (show(), not exec()) on purpose: a modal settings
        # dialog blocks input to *every other window in the app*,
        # including the login window its own "ログイン" button opens --
        # so typing into that login window required closing Settings
        # first, and closing Settings from inside its own click handler
        # while exec()'s nested loop is still unwinding was fragile (it
        # could still end up reappearing). Non-modal sidesteps the whole
        # problem: both windows just work independently.
        existing = state["settings_dialog"]
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            force_foreground(existing)
            return

        dialog = SettingsDialog(config, start_section=start_section, on_login=open_login)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # See open_login()'s matching connect() for why this is needed:
        # WA_DeleteOnClose deletes the C++ object on close, and without
        # this the next open_settings() call (e.g. via the Ctrl+Alt+S
        # hotkey) dereferences that dead object in the isVisible() check
        # below (RuntimeError: wrapped C/C++ object ... has been deleted).
        dialog.destroyed.connect(lambda: state.update(settings_dialog=None))
        state["settings_dialog"] = dialog

        def on_finished(result):
            if result:
                window.apply_window_settings()
                failed = window.reregister_hotkeys()
                if failed:
                    QMessageBox.warning(
                        None, "設定",
                        "以下のホットキーは他のアプリと重複している可能性があり、登録できませんでした:\n"
                        + "\n".join(failed),
                    )

        dialog.finished.connect(on_finished)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        force_foreground(dialog)

    startup_failed_hotkeys = window.register_hotkeys({
        "toggle_play_pause": window.toggle_play_pause,
        "next_short": window.next_short,
        "toggle_window": window.toggle_window,
        "open_settings": lambda: open_settings("使い方"),
        "toggle_info_panels": window.toggle_info_panels,
        "open_interact_window": open_interact_window,
    })
    if startup_failed_hotkeys:
        QMessageBox.warning(
            None, "OnGameShorts",
            "以下のホットキーは他のアプリ(または既に起動中の本アプリ)と重複しており、"
            "登録できませんでした。設定画面から変更できます:\n"
            + "\n".join(startup_failed_hotkeys),
        )

    # --- system tray icon: only way to quit, since the band window has
    # no titlebar/close button by design ------------------------------
    tray = QSystemTrayIcon(make_tray_icon(), app)
    tray.setToolTip("OnGameShorts")
    menu = QMenu()
    act_toggle = QAction("表示/非表示")
    act_toggle.triggered.connect(window.toggle_visibility)
    act_login = QAction("Googleアカウントにログイン...")
    act_login.triggered.connect(open_login)
    act_reload = QAction("再読み込み")
    act_reload.triggered.connect(window.reload_current)
    act_interact = QAction("この動画を大きいウィンドウで開く(コメント入力用)")
    act_interact.triggered.connect(open_interact_window)
    act_settings = QAction("設定...")
    act_settings.triggered.connect(lambda: open_settings("使い方"))
    act_quit = QAction("終了")
    act_quit.triggered.connect(app.quit)
    menu.addAction(act_toggle)
    menu.addAction(act_login)
    menu.addAction(act_reload)
    menu.addAction(act_interact)
    menu.addAction(act_settings)
    menu.addSeparator()
    menu.addAction(act_quit)
    tray.setContextMenu(menu)
    tray.show()

    if not config.get("onboarding_shown", default=False):
        config.set("onboarding_shown", True)
        config.save()
        # Login first -- without it Shorts playback is unpersonalized (or
        # stuck showing a login prompt it can't be typed into), so it's
        # the one thing worth putting in front of the user immediately
        # rather than waiting for them to find the tray menu or a hotkey.
        # The settings dialog (usage guide, hotkey list, ...) is still one
        # action away afterward via Ctrl+Alt+S or the tray menu.
        open_login()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
