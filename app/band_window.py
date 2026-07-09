"""The taskbar-resident band window: a frameless, always-on-top, focus-less
bar docked above the taskbar, with a portrait YouTube Shorts player in the
center and info panels on either side. Works alongside any foreground
application since it never steals focus.

Plays the real youtube.com/shorts page (not the IFrame Player API), signed
in via a persistent browser profile shared with the login window, so once
you've logged in once YouTube's own recommendations keep the feed flowing
continuously -- no queue management on our side.
"""
from PyQt6.QtCore import Qt, QUrl, QTimer, QEvent
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QVBoxLayout, QFrame, QSizePolicy, QPushButton,
    QSlider,
)
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
from PyQt6.QtWebEngineWidgets import QWebEngineView

from .browser_profile import get_profile
from .hotkeys import HotkeyManager
from .widgets import ToggleSwitch


# https://www.youtube.com/shorts (no video id) redirects a signed-in
# session straight into a recommended short and its swipeable feed --
# no need to seed a specific video id ourselves.
DEFAULT_START_URL = "https://www.youtube.com/shorts"

# The band window is deliberately built to never take OS focus (so it
# doesn't interrupt whatever game/app you're using), which means
# document.hasFocus() is always false from the page's point of view.
# YouTube's mobile player treats that as "backgrounded tab" and mutes +
# pauses the video shortly after it starts playing, even though it's
# fully visible on screen. Overriding hasFocus() (and swallowing blur
# events) convinces the page it's focused so it stops doing that.
# Injected at DocumentCreation -- before YouTube's own scripts run --
# so the override is in place from the very first check.
_FORCE_FOCUS_JS = r"""
(function () {
  try {
    Object.defineProperty(document, 'hasFocus', {
      value: function () { return true; },
      configurable: true,
    });
  } catch (e) {}
  window.addEventListener('blur', function (e) { e.stopImmediatePropagation(); }, true);
  document.addEventListener('visibilitychange', function (e) { e.stopImmediatePropagation(); }, true);
})();
"""

# Best-effort: hides YouTube's surrounding page chrome (mobile topbar,
# comments, etc.) so the embedded view reads as a clean vertical player in
# the small band. We load the *mobile* youtube.com layout (see
# browser_profile.py's UA), which is actually built to fit a narrow
# viewport -- unlike the desktop layout, it needs no size/position
# hacking, just hiding a bit of chrome. Selectors depend on YouTube's
# current DOM/class names and WILL need touch-ups if YouTube changes its
# markup -- disable via config["compact_style"] = false if it ever hides
# something it shouldn't.
_COMPACT_STYLE_JS = r"""
(function () {
  var HIDE_SELECTORS = [
    'ytm-mobile-topbar-renderer', '.mobile-topbar-header',
    'ytm-comments-entry-point-header-renderer', '#comments-button'
  ];
  function applyHide() {
    HIDE_SELECTORS.forEach(function (sel) {
      document.querySelectorAll(sel).forEach(function (el) {
        el.style.setProperty('display', 'none', 'important');
      });
    });
  }
  applyHide();
  new MutationObserver(applyHide).observe(document.documentElement, {
    childList: true, subtree: true
  });
})();
"""

# Hides YouTube's own on-video overlay UI (channel avatar/name, subscribe
# button, title/description, captions, the red progress/seek bar, and the
# share button) so only the video + the like/comment buttons remain -- a
# step further than compact_style, which just hides the surrounding page
# chrome. Comment/like are deliberately kept so both stay usable for
# reading -- but ytm-comment-simplebox-renderer (the "コメントする..."
# prompt at the top of the comment panel) is a fake input: tapping it is
# supposed to reveal a real text box, but that never happens in this
# embedded context (confirmed: no <textarea>/contenteditable ever shows
# up), so it's hidden too rather than leaving a compose box that silently
# eats keystrokes. Existing comments underneath it still show and scroll
# normally, just shrunk (see SHRINK_SELECTORS below) since the comment
# panel otherwise renders at full phone-screen size no matter how small
# the band window is. Separate config toggle (hide_video_ui) since this
# is a bigger visual change some people may not want.
_HIDE_VIDEO_UI_JS = r"""
(function () {
  var HIDE_SELECTORS = [
    'div.reel-player-overlay-top-bar',
    'yt-reel-channel-bar-view-model',
    'yt-shorts-video-title-view-model',
    'yt-reel-metapanel-view-model',
    '#ytp-caption-window-container',
    'yt-mweb-shorts-player-controls',
    'ytm-comment-simplebox-renderer'
  ];
  // The comment panel renders at its normal (phone-screen) size
  // regardless of our much smaller band window, so text/avatars/spacing
  // all look oversized relative to the ~170px-wide video area. zoom
  // shrinks the whole panel (and reflows it, unlike transform: scale)
  // so more fits and it reads as "small", matching the rest of the band.
  var SHRINK_SELECTORS = ['ytm-engagement-panel-section-list-renderer'];
  var SHRINK_ZOOM = '0.6';
  var KEEP_LABEL_SUBSTRINGS = ['コメント', '評価'];
  function applyHide() {
    HIDE_SELECTORS.forEach(function (sel) {
      document.querySelectorAll(sel).forEach(function (el) {
        el.style.setProperty('display', 'none', 'important');
      });
    });
    SHRINK_SELECTORS.forEach(function (sel) {
      document.querySelectorAll(sel).forEach(function (el) {
        el.style.setProperty('zoom', SHRINK_ZOOM, 'important');
      });
    });
    document.querySelectorAll('reel-action-bar-view-model button').forEach(function (btn) {
      var label = btn.getAttribute('aria-label') || '';
      var keep = KEEP_LABEL_SUBSTRINGS.some(function (s) { return label.indexOf(s) !== -1; });
      if (!keep) {
        var wrapper = btn.closest('button-view-model') || btn;
        wrapper.style.setProperty('display', 'none', 'important');
      }
    });
  }
  applyHide();
  new MutationObserver(applyHide).observe(document.documentElement, {
    childList: true, subtree: true
  });
})();
"""

# Volume and autoplay-to-next-short state, kept in the page (like
# window.__ogsWantPlaying above) so it survives YouTube swapping in a new
# <video> element for each short. window.__ogsApplyVolume is the single
# place that touches volume/muted, so the play/resume/gesture handlers
# below stay consistent with a volume slider set to 0 instead of fighting
# it with their own "unmute on play" logic.
_VOLUME_AUTOPLAY_JS_TEMPLATE = r"""
(function () {
  if (window.__ogsVolume === undefined) window.__ogsVolume = __OGS_INITIAL_VOLUME__;
  if (window.__ogsAutoplay === undefined) window.__ogsAutoplay = __OGS_INITIAL_AUTOPLAY__;

  window.__ogsApplyVolume = function (el) {
    el.volume = window.__ogsVolume;
    el.muted = window.__ogsVolume <= 0;
  };

  window.__ogsSetVolume = function (v) {
    window.__ogsVolume = v;
    var el = document.querySelector('ytd-reel-video-renderer[is-active] video')
         || document.querySelector('video');
    if (el) window.__ogsApplyVolume(el);
  };

  function goNext() {
    document.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'ArrowDown', code: 'ArrowDown', keyCode: 40, which: 40, bubbles: true
    }));
  }

  window.__ogsSetAutoplay = function (b) {
    window.__ogsAutoplay = b;
    var el = document.querySelector('ytd-reel-video-renderer[is-active] video')
         || document.querySelector('video');
    if (el) el.loop = !b;
  };

  // Shorts set the native loop attribute so the browser replays the video
  // on its own once it ends -- and per spec, looping a video that way
  // never fires 'ended' at all, which is why watching for 'ended' alone
  // didn't work. Turning loop off (only while autoplay-to-next is on)
  // restores real 'ended' events instead of us having to guess a loop
  // restart from currentTime jitter, which false-positived on ordinary
  // buffering stalls and skipped to the next short mid-video.
  function applyState(v) {
    window.__ogsApplyVolume(v);
    v.loop = !window.__ogsAutoplay;
  }

  function bind() {
    var v = document.querySelector('video');
    if (!v) return;
    // Shorts reuse a single <video> element across shorts (swapping its
    // source) rather than creating a new one each time, so loop/volume
    // must be reapplied on every source change, not just once -- YouTube
    // resets loop back to true itself whenever a new short loads.
    // 'durationchange' reliably fires on each source swap (each short has
    // a different duration) as well as for the first video.
    applyState(v);
    if (v.__ogsVolBound) return;
    v.__ogsVolBound = true;
    v.addEventListener('durationchange', function () { applyState(v); });
    v.addEventListener('ended', function () {
      if (window.__ogsAutoplay) goNext();
    });
  }
  bind();
  new MutationObserver(bind).observe(document.documentElement, {
    childList: true, subtree: true
  });
})();
"""

# YouTube's mobile player intermittently pauses (and mutes) playback on
# its own a couple seconds in, even with the hasFocus()/backgrounding
# fixes above -- possibly an internal buffering/stall heuristic. Polling
# to un-pause it is too slow (visible stutter), so instead we listen for
# the 'pause' event directly and resume the instant it fires, but only
# while we actually want it playing (tracked via window.__ogsWantPlaying,
# set by _PLAY_JS/_PAUSE_JS below) so a real user-requested pause sticks.
# Rebinds via MutationObserver since YouTube swaps in a new <video> for
# each short.
_AUTO_RESUME_JS = r"""
(function () {
  if (window.__ogsWantPlaying === undefined) window.__ogsWantPlaying = true;
  var MAX_RESUME_DELAY_MS = 2000;
  var STABLE_PLAYBACK_MS = 2000;

  function bind() {
    var v = document.querySelector('video');
    if (!v || v.__ogsBound) return;
    v.__ogsBound = true;
    v.__ogsResumeAttempts = 0;

    // Measured: some videos get paused by something outside our control
    // (not buffering -- readyState stays HAVE_ENOUGH_DATA throughout) a
    // few hundred ms after *any* play() call, repeatedly, regardless of
    // window size or focus state -- root cause not fully pinned down, but
    // resuming forever just re-triggers it every time, which is audible
    // as continuous crackling. Retrying a bounded number of times with
    // backoff recovers the common case (a couple of early hiccups) without
    // fighting an unrecoverable case indefinitely.
    v.addEventListener('pause', function () {
      // v.ended means this pause is the video reaching its natural end
      // (only possible now that autoplay-to-next sets loop=false) -- that
      // must be left alone for the 'ended' handler (_VOLUME_AUTOPLAY_JS)
      // to react to, not resumed here, or the two fight: this would
      // restart the finished video from 0 right as the other handler
      // tries to advance to the next short.
      if (!window.__ogsWantPlaying || v.ended) return;
      if (v.__ogsResumeScheduled) return;
      v.__ogsResumeScheduled = true;
      // Retries forever (never gives up -- a video that never gets to
      // keep playing is worse than one that occasionally blips), but
      // backs off exponentially up to MAX_RESUME_DELAY_MS so a
      // persistently-fighting video settles into a quiet ~2s cadence
      // instead of crackling continuously.
      var delay = Math.min(150 * Math.pow(2, v.__ogsResumeAttempts), MAX_RESUME_DELAY_MS);
      setTimeout(function () {
        v.__ogsResumeScheduled = false;
        if (v.paused && !v.ended && window.__ogsWantPlaying) {
          v.__ogsResumeAttempts++;
          if (window.__ogsApplyVolume) window.__ogsApplyVolume(v);
          v.play().catch(function () {});
        }
      }, delay);
    });

    // Once playback has actually held steady for a while, treat any prior
    // struggle as over and give a fresh retry budget for next time. Each
    // new 'playing' cancels the previous pending check, so as long as
    // pause/playing keeps firing in a tight loop this check keeps getting
    // pushed out and never actually resets the budget -- only a genuine
    // >=2s hold (no further 'playing' events) counts as recovered.
    v.addEventListener('playing', function () {
      if (v.__ogsStableCheckTimer) clearTimeout(v.__ogsStableCheckTimer);
      v.__ogsStableCheckTimer = setTimeout(function () {
        if (!v.paused) v.__ogsResumeAttempts = 0;
      }, STABLE_PLAYBACK_MS);
    });

    // Shorts reuse a single <video> element across shorts, so a retry
    // budget exhausted on one short must not carry over and permanently
    // silence recovery for every short after it.
    v.addEventListener('durationchange', function () {
      v.__ogsResumeAttempts = 0;
    });
  }
  bind();
  new MutationObserver(bind).observe(document.documentElement, {
    childList: true, subtree: true
  });
})();
"""

_PLAY_JS = r"""
(function () {
  window.__ogsWantPlaying = true;
  var v = document.querySelector('ytd-reel-video-renderer[is-active] video')
       || document.querySelector('video');
  if (!v) return;
  if (window.__ogsApplyVolume) window.__ogsApplyVolume(v);
  v.play().catch(function () {});
})();
"""

_PAUSE_JS = r"""
(function () {
  window.__ogsWantPlaying = false;
  var v = document.querySelector('ytd-reel-video-renderer[is-active] video')
       || document.querySelector('video');
  if (v) v.pause();
})();
"""

# window.__ogsWantPlaying is the single source of truth for "should this
# be playing", shared between the hotkey-driven play()/pause() above, the
# click-to-toggle gesture handler below, and the auto-resume watchdog
# (_AUTO_RESUME_JS) that recovers from YouTube's own unwanted pauses.
# Toggling it here (rather than in Python) means a click-driven pause and
# a subsequent hotkey press stay consistent with each other.
_TOGGLE_PLAY_PAUSE_JS = r"""
(function () {
  var v = document.querySelector('ytd-reel-video-renderer[is-active] video')
       || document.querySelector('video');
  if (!v) return;
  window.__ogsWantPlaying = !window.__ogsWantPlaying;
  if (window.__ogsWantPlaying) {
    if (window.__ogsApplyVolume) window.__ogsApplyVolume(v);
    v.play().catch(function () {});
  } else { v.pause(); }
})();
"""

# YouTube's Shorts player treats Up/Down (and J/K) as prev/next-short
# shortcuts. Simulated as a synthetic keydown on document since we don't
# control the page's own script.
_NEXT_SHORT_JS = r"""
(function () {
  document.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'ArrowDown', code: 'ArrowDown', keyCode: 40, which: 40, bubbles: true
  }));
})();
"""

# Click the video to toggle play/pause; drag/swipe vertically past a
# threshold to advance to the next short -- desktop-mouse equivalents of
# the tap-to-pause / swipe-up gestures you'd use on an actual phone.
# Listens on the whole document (capture phase) but skips anything that
# started on an interactive element (buttons, the comment bottom-sheet)
# so those keep working normally -- e.g. scrolling through comments with
# the mouse shouldn't be mistaken for a swipe-to-next.
_GESTURES_JS = r"""
(function () {
  var SWIPE_THRESHOLD_PX = 40;
  var startX = null, startY = null, startedOnInteractive = false;

  function isInteractive(el) {
    return !!(el && el.closest && el.closest(
      'button, a, input, textarea, [contenteditable="true"], ' +
      'ytm-bottom-sheet-renderer, reel-action-bar-view-model'
    ));
  }

  function onDown(e) {
    startX = e.clientX;
    startY = e.clientY;
    startedOnInteractive = isInteractive(e.target);
  }

  function onUp(e) {
    if (startX === null || startedOnInteractive) {
      startX = null;
      return;
    }
    var dx = e.clientX - startX;
    var dy = e.clientY - startY;
    startX = null;

    if (Math.abs(dy) >= SWIPE_THRESHOLD_PX && Math.abs(dy) > Math.abs(dx)) {
      if (dy < 0) {
        document.dispatchEvent(new KeyboardEvent('keydown', {
          key: 'ArrowDown', code: 'ArrowDown', keyCode: 40, which: 40, bubbles: true
        }));
      }
      return;
    }

    var v = document.querySelector('ytd-reel-video-renderer[is-active] video')
         || document.querySelector('video');
    if (!v) return;
    window.__ogsWantPlaying = !window.__ogsWantPlaying;
    if (window.__ogsWantPlaying) {
      if (window.__ogsApplyVolume) window.__ogsApplyVolume(v);
      v.play().catch(function () {});
    } else { v.pause(); }
  }

  document.addEventListener('mousedown', onDown, true);
  document.addEventListener('mouseup', onUp, true);
})();
"""


def _hotkey_summary(spec):
    mods = "+".join(m.capitalize() for m in spec.get("modifiers", []))
    key = spec.get("key", "?")
    return f"{mods}+{key}" if mods else key


class BandWindow(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self._hotkey_manager = None
        self._hotkey_actions = {}
        self._drag_offset = None

        self._init_window()
        self._init_ui()

        self._title_timer = QTimer(self)
        self._title_timer.setInterval(2000)
        self._title_timer.timeout.connect(self._poll_title)
        self._title_timer.start()

        # YouTube's mobile player sometimes auto-pauses/mutes itself a
        # moment after starting (seemingly treating the never-focused band
        # window as backgrounded despite the hasFocus() override below).
        # Recovery from that lives entirely in JS now (_AUTO_RESUME_JS,
        # event-driven off the 'pause' event) rather than a Python-side
        # timer blindly re-asserting play() -- a blind timer would fight
        # a real click-to-pause from _GESTURES_JS, which it has no way to
        # know about.

    # ------------------------------------------------------------------ UI

    def _effective_width(self):
        """The title/hotkey side panels can be hidden (config
        show_info_panels) to make a slim video-only band -- in that case
        the configured window width is ignored in favor of a width that
        just fits the video."""
        if self.config.get("show_info_panels", default=True):
            return self.config.get("window", "width", default=600)
        h = self.config.get("window", "height", default=340)
        video_h = max(120, h - 40)
        video_w = max(80, round(video_h * 9 / 16))
        return video_w + 24  # matches the panel's left+right content margins

    def _init_window(self):
        # setWindowFlags() forces Qt to recreate the native window, which
        # discards/undoes a resize() that ran just before it and can leave
        # the window stuck at a stale size on subsequent calls. So this
        # (flags/attributes) only ever runs once, here; anything that needs
        # to re-apply size/position later (settings changes, panel toggle)
        # calls _apply_geometry() instead, never this.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._apply_geometry()

    def _apply_geometry(self):
        w = self._effective_width()
        h = self.config.get("window", "height", default=340)
        # QLayout::activate() sets the top-level widget's minimumSize()
        # from the layout's computed minimum, and that stuck minimum
        # doesn't shrink back down on its own just because a child got
        # hidden -- it has to be cleared explicitly or resize() below
        # gets silently clamped back up to the old (larger) minimum.
        self.setMinimumSize(0, 0)
        self.resize(w, h)

        x = self.config.get("window", "x", default=None)
        y = self.config.get("window", "y", default=None)
        if x is None or y is None:
            screen = QGuiApplication.primaryScreen()
            geo = screen.availableGeometry()
            margin_bottom = self.config.get("window", "margin_bottom", default=4)
            x = geo.x() + (geo.width() - w) // 2
            y = geo.y() + geo.height() - h - margin_bottom
        self.move(x, y)

    def _init_ui(self):
        self.setStyleSheet(
            """
            BandWindow { background: transparent; }
            #panel { background-color: rgba(18, 18, 22, 235); border-radius: 10px; }
            QLabel { color: #e8e8ec; }
            #heading { color: #9fd2ff; font-weight: bold; }
            QLabel[class="keyBadge"] {
                background-color: #101014;
                border: 1px solid #33333d;
                border-radius: 5px;
                padding: 1px 6px;
                color: #9fd2ff;
                font-family: Consolas, monospace;
            }
            QLabel[class="actionLabel"] { color: #cfcfd8; }
            #dragHint { color: #6f6f7a; font-size: 9pt; }
            QPushButton#closeButton {
                background-color: rgba(255, 255, 255, 18);
                color: #cfcfd8;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                padding: 0;
            }
            QPushButton#closeButton:hover {
                background-color: #c0392b;
                color: white;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: #33333d;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                height: 4px;
                background: #9fd2ff;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 12px;
                margin: -5px 0;
                background: #e8e8ec;
                border-radius: 6px;
            }
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        panel = QFrame(self)
        panel.setObjectName("panel")
        outer.addWidget(panel)

        row = QHBoxLayout(panel)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)
        self._row_layout = row

        # -- left info panel: current title --------------------------------
        left = QVBoxLayout()
        left.setSpacing(4)
        heading = QLabel("再生中のShorts")
        heading.setObjectName("heading")
        self.title_label = QLabel("(読み込み中...)")
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignTop)

        left.addWidget(heading)
        left.addWidget(self.title_label, 1)
        left.addStretch(1)

        volume_row = QHBoxLayout()
        volume_row.setSpacing(6)
        volume_label = QLabel("音量")
        volume_label.setProperty("class", "actionLabel")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.config.get("volume", default=80))
        self.volume_slider.valueChanged.connect(self.set_volume)
        volume_row.addWidget(volume_label, 0)
        volume_row.addWidget(self.volume_slider, 1)
        left.addLayout(volume_row)

        autoplay_row = QHBoxLayout()
        autoplay_row.setSpacing(6)
        autoplay_label = QLabel("自動再生")
        autoplay_label.setProperty("class", "actionLabel")
        initial_autoplay = self.config.get("autoplay", default=True)
        self.autoplay_toggle = ToggleSwitch()
        self.autoplay_toggle.setChecked(initial_autoplay)
        self.autoplay_toggle.toggled.connect(self.set_autoplay)
        autoplay_row.addWidget(autoplay_label, 0)
        autoplay_row.addStretch(1)
        autoplay_row.addWidget(self.autoplay_toggle, 0)
        left.addLayout(autoplay_row)

        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.left_widget = left_widget

        # -- center: portrait video player -------------------------------
        h = self.config.get("window", "height", default=340)
        video_h = max(120, h - 40)
        video_w = max(80, round(video_h * 9 / 16))
        self.web_view = QWebEngineView()
        self.web_view.setFixedSize(video_w, video_h)
        self.web_view.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # The page must be fully configured (setPage + scripts + load)
        # *before* the view is inserted into a layout below -- doing it
        # after triggers a native crash in this Qt6 build when the window
        # is realized.
        self._init_webview()

        # -- right info panel: hotkey list ---------------------------------
        right = QVBoxLayout()
        right.setSpacing(6)
        hotkeys_heading = QLabel("ホットキー")
        hotkeys_heading.setObjectName("heading")
        right.addWidget(hotkeys_heading)

        self._hotkey_rows_layout = QVBoxLayout()
        self._hotkey_rows_layout.setSpacing(4)
        right.addLayout(self._hotkey_rows_layout)

        drag_hint = QLabel("ドラッグで移動できます")
        drag_hint.setObjectName("dragHint")
        right.addWidget(drag_hint)
        right.addStretch(1)
        self.refresh_hotkey_labels()

        right_widget = QWidget()
        right_widget.setLayout(right)
        right_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.right_widget = right_widget

        row.addWidget(left_widget, 1)
        row.addWidget(self.web_view, 0)
        row.addWidget(right_widget, 1)

        self.apply_panel_visibility()

        # -- drag-to-move: grab anywhere on the panel except the video ------
        for draggable in (panel, left_widget, right_widget):
            draggable.installEventFilter(self)
            draggable.setCursor(Qt.CursorShape.SizeAllCursor)

        # -- close button: hides the window (same as Ctrl+Alt+H) -----------
        self.close_button = QPushButton("✕", self)
        self.close_button.setObjectName("closeButton")
        self.close_button.setFixedSize(20, 20)
        self.close_button.setCursor(Qt.CursorShape.ArrowCursor)
        self.close_button.clicked.connect(self.hide)
        self.close_button.raise_()
        self._position_close_button()

    def _position_close_button(self):
        if hasattr(self, "close_button"):
            self.close_button.move(self.width() - self.close_button.width() - 8, 8)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_close_button()

    def refresh_hotkey_labels(self):
        while self._hotkey_rows_layout.count():
            item = self._hotkey_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        hk = self.config.get("hotkeys", default={})
        rows = [
            ("再生/一時停止", hk.get("toggle_play_pause", {})),
            ("次のShorts", hk.get("next_short", {})),
            ("表示/非表示", hk.get("toggle_window", {})),
            ("設定を開く", hk.get("open_settings", {})),
            ("タイトル/ホットキー欄の表示切替", hk.get("toggle_info_panels", {})),
            ("大きいウィンドウで開く", hk.get("open_interact_window", {})),
        ]
        for description, spec in rows:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)

            action_label = QLabel(description)
            action_label.setProperty("class", "actionLabel")
            badge = QLabel(_hotkey_summary(spec))
            badge.setProperty("class", "keyBadge")

            row_layout.addWidget(action_label, 1)
            row_layout.addWidget(badge, 0)
            self._hotkey_rows_layout.addWidget(row_widget)

    def _init_webview(self):
        # Keep a strong Python-side reference to the profile/page: if only
        # C++ parent ownership holds them, PyQt6 can garbage-collect the
        # Python wrapper while QtWebEngine's async init is still in flight,
        # which crashes the process on show(). See README known issues.
        self._profile = get_profile()
        self._page = QWebEnginePage(self._profile, self.web_view)
        self.web_view.setPage(self._page)

        self._force_focus_script = QWebEngineScript()
        self._force_focus_script.setName("ongameshorts-force-focus")
        self._force_focus_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        self._force_focus_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        self._force_focus_script.setRunsOnSubFrames(True)
        self._force_focus_script.setSourceCode(_FORCE_FOCUS_JS)
        self._page.scripts().insert(self._force_focus_script)

        volume_pct = self.config.get("volume", default=80)
        autoplay = self.config.get("autoplay", default=True)
        self._volume_autoplay_script = QWebEngineScript()
        self._volume_autoplay_script.setName("ongameshorts-volume-autoplay")
        self._volume_autoplay_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        self._volume_autoplay_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        self._volume_autoplay_script.setRunsOnSubFrames(False)
        volume_autoplay_source = (
            _VOLUME_AUTOPLAY_JS_TEMPLATE
            .replace("__OGS_INITIAL_VOLUME__", str(max(0, min(100, volume_pct)) / 100))
            .replace("__OGS_INITIAL_AUTOPLAY__", "true" if autoplay else "false")
        )
        self._volume_autoplay_script.setSourceCode(volume_autoplay_source)
        self._page.scripts().insert(self._volume_autoplay_script)

        if self.config.get("compact_style", default=True):
            self._compact_style_script = QWebEngineScript()
            self._compact_style_script.setName("ongameshorts-compact-style")
            self._compact_style_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
            self._compact_style_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            self._compact_style_script.setRunsOnSubFrames(False)
            self._compact_style_script.setSourceCode(_COMPACT_STYLE_JS)
            self._page.scripts().insert(self._compact_style_script)

        if self.config.get("hide_video_ui", default=True):
            self._hide_video_ui_script = QWebEngineScript()
            self._hide_video_ui_script.setName("ongameshorts-hide-video-ui")
            self._hide_video_ui_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
            self._hide_video_ui_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            self._hide_video_ui_script.setRunsOnSubFrames(False)
            self._hide_video_ui_script.setSourceCode(_HIDE_VIDEO_UI_JS)
            self._page.scripts().insert(self._hide_video_ui_script)

        self._auto_resume_script = QWebEngineScript()
        self._auto_resume_script.setName("ongameshorts-auto-resume")
        self._auto_resume_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        self._auto_resume_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        self._auto_resume_script.setRunsOnSubFrames(False)
        self._auto_resume_script.setSourceCode(_AUTO_RESUME_JS)
        self._page.scripts().insert(self._auto_resume_script)

        self._gestures_script = QWebEngineScript()
        self._gestures_script.setName("ongameshorts-gestures")
        self._gestures_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        self._gestures_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        self._gestures_script.setRunsOnSubFrames(False)
        self._gestures_script.setSourceCode(_GESTURES_JS)
        self._page.scripts().insert(self._gestures_script)

        # The mobile Shorts layout doesn't reliably autoplay on its own --
        # give it an explicit play() once the page (and, after navigating
        # to a specific short, the redirect) has settled.
        self.web_view.loadFinished.connect(self._on_load_finished)

        self.web_view.load(QUrl(DEFAULT_START_URL))

    def _run_js(self, code):
        self.web_view.page().runJavaScript(code)

    def _on_load_finished(self, ok):
        if ok:
            QTimer.singleShot(800, self.play)

    def next_short(self):
        self._run_js(_NEXT_SHORT_JS)

    # ------------------------------------------------------------- actions

    def play(self):
        self._run_js(_PLAY_JS)

    def pause(self):
        self._run_js(_PAUSE_JS)

    def toggle_play_pause(self):
        # Decided in JS (window.__ogsWantPlaying), not cached Python state,
        # so this stays consistent with clicks/swipes handled by
        # _GESTURES_JS -- those update the same flag directly in the page.
        self._run_js(_TOGGLE_PLAY_PAUSE_JS)

    def set_volume(self, value):
        """value: 0-100. Applied live to the current video and persisted so
        the next launch (and the next short YouTube swaps in) keeps it."""
        value = max(0, min(100, int(value)))
        self._run_js(f"window.__ogsSetVolume && window.__ogsSetVolume({value / 100});")
        self.config.set("volume", value)
        self.config.save()

    def set_autoplay(self, enabled):
        """When on, advancing to the next short happens automatically once
        the current one finishes playing (in addition to the manual
        next_short hotkey, which always works either way)."""
        self._run_js(f"window.__ogsSetAutoplay && window.__ogsSetAutoplay({'true' if enabled else 'false'});")
        self.config.set("autoplay", bool(enabled))
        self.config.save()

    def toggle_visibility(self):
        self.hide() if self.isVisible() else self.show()

    def toggle_window(self):
        self.toggle_visibility()

    def reload_current(self):
        """Re-navigate to the Shorts feed (e.g. after signing in)."""
        self.web_view.load(QUrl(DEFAULT_START_URL))

    def get_current_url(self, callback):
        """Fetches the currently-playing short's URL asynchronously (used
        to open the same video in a focusable InteractWindow for typing
        comments etc.)."""
        self.web_view.page().runJavaScript("location.href", callback)

    # ----------------------------------------------------------------- title

    def _poll_title(self):
        self.web_view.page().runJavaScript("document.title", self._on_title_result)

    def _on_title_result(self, title):
        if not title:
            return
        cleaned = title.replace(" - YouTube", "").strip()
        if cleaned:
            self.title_label.setText(cleaned)

    # -------------------------------------------------------- apply settings

    def apply_panel_visibility(self):
        show = self.config.get("show_info_panels", default=True)
        self.left_widget.setVisible(show)
        self.right_widget.setVisible(show)
        # setVisible() only *posts* a layout-invalidation event -- it's
        # processed on the next event loop pass, not immediately. Without
        # forcing it now, an immediately-following resize() gets clamped
        # against the layout's stale (pre-hide) minimum size, so the
        # window doesn't actually shrink until some later, unrelated
        # event loop pass forces a relayout.
        self._row_layout.activate()

    def toggle_info_panels(self):
        """Flips show_info_panels and re-applies it live (window width
        included) -- bound to a hotkey so it doesn't require opening
        Settings."""
        show = not self.config.get("show_info_panels", default=True)
        self.config.set("show_info_panels", show)
        self.config.save()
        self.apply_window_settings()

    def apply_window_settings(self):
        """Re-reads window size/position from config and applies it live
        (called after the settings dialog is saved)."""
        self.apply_panel_visibility()
        self._apply_geometry()
        h = self.config.get("window", "height", default=340)
        video_h = max(120, h - 40)
        video_w = max(80, round(video_h * 9 / 16))
        self.web_view.setFixedSize(video_w, video_h)
        self._position_close_button()

    # ------------------------------------------------------------ hotkeys

    def register_hotkeys(self, actions):
        """actions: dict name -> callable, matching keys in config['hotkeys'].
        Returns a list of action names that failed to register (e.g. combo
        already taken by another app or another running copy of this app) --
        those are skipped rather than raising, so one conflicting hotkey
        doesn't take down the whole app on startup."""
        self._hotkey_actions = actions
        hwnd = int(self.winId())
        self._hotkey_manager = HotkeyManager(hwnd)
        hk_config = self.config.get("hotkeys", default={})
        failed = []
        for name, callback in actions.items():
            spec = hk_config.get(name)
            if not spec:
                continue
            try:
                self._hotkey_manager.register(name, spec, callback)
            except OSError:
                failed.append(name)
        return failed

    def reregister_hotkeys(self):
        """Unregisters and re-registers all hotkeys from the current config
        (called after the settings dialog is saved). Returns a list of
        action names that failed to register (e.g. combo already taken by
        another app)."""
        if self._hotkey_manager is not None:
            self._hotkey_manager.unregister_all()

        hwnd = int(self.winId())
        self._hotkey_manager = HotkeyManager(hwnd)
        hk_config = self.config.get("hotkeys", default={})
        failed = []
        for name, callback in self._hotkey_actions.items():
            spec = hk_config.get(name)
            if not spec:
                continue
            try:
                self._hotkey_manager.register(name, spec, callback)
            except OSError:
                failed.append(name)

        self.refresh_hotkey_labels()
        return failed

    # ------------------------------------------------------------ dragging

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            return True
        if etype == QEvent.Type.MouseMove and self._drag_offset is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True
        if etype == QEvent.Type.MouseButtonRelease and self._drag_offset is not None:
            self._drag_offset = None
            self._save_position()
            return True
        return super().eventFilter(obj, event)

    def _save_position(self):
        self.config.set("window", "x", self.x())
        self.config.set("window", "y", self.y())
        self.config.save()

    def closeEvent(self, event):
        if self._hotkey_manager is not None:
            self._hotkey_manager.unregister_all()
        super().closeEvent(event)
