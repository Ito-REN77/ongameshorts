"""Dark, card-style settings dialog: a left-hand section list next to a
stacked panel (usage guide / window / hotkeys / display), styled as
minimal dark cards. Opened from the tray menu, and automatically on first
launch to double as the usage guide."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QListWidget, QListWidgetItem, QStackedWidget, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QCheckBox,
    QPushButton, QFrame, QGridLayout, QMessageBox, QLineEdit, QSizePolicy,
)

MOD_ORDER = ["ctrl", "alt", "shift", "win"]
MOD_LABELS = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}

HOTKEY_ACTIONS = [
    ("toggle_play_pause", "再生 / 一時停止"),
    ("next_short", "次のShortsへスキップ"),
    ("toggle_window", "ウィンドウの表示 / 非表示"),
    ("open_settings", "設定を開く"),
    ("toggle_info_panels", "タイトル/ホットキー欄の表示切替"),
    ("open_interact_window", "大きいウィンドウで開く(コメント入力用)"),
]

DIALOG_QSS = """
QDialog { background-color: #121216; }
QLabel { color: #e8e8ec; }
QLabel[role="heading"] { color: #9fd2ff; font-size: 14pt; font-weight: bold; }
QLabel[role="subtext"] { color: #9a9aa5; }
#navList {
    background-color: #17171c;
    border: none;
    border-radius: 10px;
    padding: 6px;
    outline: none;
}
#navList::item {
    color: #cfcfd8;
    padding: 10px 12px;
    border-radius: 8px;
    margin: 2px 0;
}
#navList::item:selected {
    background-color: #26262f;
    color: #9fd2ff;
}
QFrame[class="card"] {
    background-color: #1a1a20;
    border: 1px solid #2a2a33;
    border-radius: 10px;
}
QPlainTextEdit, QSpinBox, QLineEdit {
    background-color: #101014;
    color: #e8e8ec;
    border: 1px solid #33333d;
    border-radius: 6px;
    padding: 4px 6px;
}
QCheckBox { color: #e8e8ec; }
QPushButton {
    background-color: #23232b;
    color: #e8e8ec;
    border: 1px solid #33333d;
    border-radius: 8px;
    padding: 8px 18px;
}
QPushButton:hover { background-color: #2c2c36; }
QPushButton[role="primary"] {
    background-color: #3a6fb0;
    border: 1px solid #4c86cc;
    color: white;
}
QPushButton[role="primary"]:hover { background-color: #4380c9; }
QLabel[class="keyBadge"] {
    background-color: #101014;
    border: 1px solid #33333d;
    border-radius: 6px;
    padding: 3px 8px;
    color: #9fd2ff;
    font-family: Consolas, monospace;
}
"""


def _card(inner_layout):
    frame = QFrame()
    frame.setProperty("class", "card")
    frame.setLayout(inner_layout)
    return frame


def _heading(text):
    label = QLabel(text)
    label.setProperty("role", "heading")
    return label


def _subtext(text):
    label = QLabel(text)
    label.setProperty("role", "subtext")
    label.setWordWrap(True)
    return label


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None, start_section="使い方", on_login=None):
        super().__init__(parent)
        self.config = config
        self._on_login = on_login
        self.setWindowTitle("設定 - OnGameShorts")
        # Reject/accept only hides a QDialog by default -- the object (and
        # its native window) stays alive. Destroying it on close rules out
        # anything later (a stray reference, a delayed call queued before
        # it closed) from ever making it reappear.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(680, 480)
        self.setStyleSheet(DIALOG_QSS)

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        self.nav = QListWidget()
        self.nav.setObjectName("navList")
        self.nav.setFixedWidth(160)
        self.nav.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self.stack = QStackedWidget()

        sections = [
            ("使い方", self._build_usage_page),
            ("ウィンドウ", self._build_window_page),
            ("ホットキー", self._build_hotkeys_page),
            ("表示", self._build_display_page),
        ]
        section_names = []
        for name, builder in sections:
            self.nav.addItem(QListWidgetItem(name))
            self.stack.addWidget(builder())
            section_names.append(name)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        start_index = section_names.index(start_section) if start_section in section_names else 0
        self.nav.setCurrentRow(start_index)

        right = QVBoxLayout()
        right.addWidget(self.stack, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("保存")
        save_btn.setProperty("role", "primary")
        save_btn.clicked.connect(self._save)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        right.addLayout(buttons)

        root.addWidget(self.nav)
        root.addLayout(right, 1)

    # ------------------------------------------------------------- pages

    def _build_usage_page(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.addWidget(_heading("使い方"))

        guide = QLabel(
            "画面下部・タスクバー直上にウィンドウが常駐し、YouTube Shortsのおすすめを流します。\n"
            "他のアプリを操作したまま、下のホットキーで操作できます。\n\n"
            "① タスクトレイのアイコンを右クリック →「Googleアカウントにログイン...」でログイン\n"
            "② ログインするだけで、自動的にYouTubeのおすすめのShortsが流れ始めます\n\n"
            "設定はいつでもタスクトレイ →「設定...」、またはホットキーで開けます。"
        )
        guide.setWordWrap(True)

        login_btn = QPushButton("Googleアカウントにログイン...")
        login_btn.setProperty("role", "primary")
        login_btn.clicked.connect(self._handle_login_click)
        login_row = QHBoxLayout()
        login_row.addWidget(login_btn)
        login_row.addStretch(1)

        guide_card_layout = QVBoxLayout()
        guide_card_layout.addWidget(guide)
        guide_card_layout.addLayout(login_row)
        layout.addWidget(_card(guide_card_layout))

        layout.addWidget(_heading("ホットキー一覧"))
        hk_layout = QVBoxLayout()
        hk = self.config.get("hotkeys", default={})
        for name, description in HOTKEY_ACTIONS:
            hk_layout.addLayout(_hotkey_row(description, hk.get(name, {})))
        layout.addWidget(_card(hk_layout))

        layout.addStretch(1)
        return _page(layout)

    def _build_window_page(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.addWidget(_heading("ウィンドウ"))

        grid = QGridLayout()
        grid.setSpacing(8)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(300, 1400)
        self.width_spin.setValue(self.config.get("window", "width", default=600))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(160, 900)
        self.height_spin.setValue(self.config.get("window", "height", default=340))
        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(0, 200)
        self.margin_spin.setValue(self.config.get("window", "margin_bottom", default=4))

        grid.addWidget(QLabel("幅 (px)"), 0, 0)
        grid.addWidget(self.width_spin, 0, 1)
        grid.addWidget(QLabel("高さ (px)"), 1, 0)
        grid.addWidget(self.height_spin, 1, 1)
        grid.addWidget(QLabel("画面下端からの余白 (px)"), 2, 0)
        grid.addWidget(self.margin_spin, 2, 1)

        self.auto_position_check = QCheckBox("画面下部中央に自動配置する")
        cur_x = self.config.get("window", "x", default=None)
        cur_y = self.config.get("window", "y", default=None)
        self.auto_position_check.setChecked(cur_x is None or cur_y is None)

        self.x_spin = QSpinBox()
        self.x_spin.setRange(0, 10000)
        self.x_spin.setValue(cur_x or 0)
        self.y_spin = QSpinBox()
        self.y_spin.setRange(0, 10000)
        self.y_spin.setValue(cur_y or 0)

        grid.addWidget(self.auto_position_check, 3, 0, 1, 2)
        grid.addWidget(QLabel("X座標"), 4, 0)
        grid.addWidget(self.x_spin, 4, 1)
        grid.addWidget(QLabel("Y座標"), 5, 0)
        grid.addWidget(self.y_spin, 5, 1)

        def _sync_manual_pos_enabled():
            enabled = not self.auto_position_check.isChecked()
            self.x_spin.setEnabled(enabled)
            self.y_spin.setEnabled(enabled)

        self.auto_position_check.toggled.connect(lambda _checked: _sync_manual_pos_enabled())
        _sync_manual_pos_enabled()

        layout.addWidget(_card(grid))
        layout.addStretch(1)
        return _page(layout)

    def _build_hotkeys_page(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.addWidget(_heading("ホットキー"))
        layout.addWidget(_subtext(
            "使用中の他アプリのキー割り当てと被らない組み合わせを選んでください。"
        ))

        self._hotkey_widgets = {}
        hk = self.config.get("hotkeys", default={})

        grid_wrap = QVBoxLayout()
        for name, description in HOTKEY_ACTIONS:
            spec = hk.get(name, {"modifiers": [], "key": ""})
            row = QHBoxLayout()
            row.addWidget(QLabel(description), 1)

            mod_checks = {}
            for mod in MOD_ORDER:
                cb = QCheckBox(MOD_LABELS[mod])
                cb.setChecked(mod in spec.get("modifiers", []))
                row.addWidget(cb)
                mod_checks[mod] = cb

            key_edit = QLineEdit(spec.get("key", ""))
            key_edit.setMaxLength(1)
            key_edit.setFixedWidth(36)
            key_edit.textChanged.connect(
                lambda text, e=key_edit: e.setText(text.upper()[-1:]) if text else None
            )
            row.addWidget(key_edit)

            self._hotkey_widgets[name] = {"mods": mod_checks, "key": key_edit}
            grid_wrap.addLayout(row)

        layout.addWidget(_card(grid_wrap))
        layout.addStretch(1)
        return _page(layout)

    def _build_display_page(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.addWidget(_heading("表示"))

        self.compact_style_check = QCheckBox(
            "YouTubeのヘッダー/コメント欄などを非表示にする (compact_style)"
        )
        self.compact_style_check.setChecked(self.config.get("compact_style", default=True))
        note = _subtext(
            "YouTube側のページ構造に依存するベストエフォートの機能です。"
            "うまく表示されない場合はオフにしてください。反映には再読み込みが必要です。"
        )

        inner = QVBoxLayout()
        inner.addWidget(self.compact_style_check)
        inner.addWidget(note)
        layout.addWidget(_card(inner))

        self.hide_video_ui_check = QCheckBox(
            "動画上のYouTube UI(チャンネル名・いいね・共有・字幕・進捗バーなど)を非表示にする"
        )
        self.hide_video_ui_check.setChecked(self.config.get("hide_video_ui", default=True))
        hide_ui_note = _subtext(
            "動画そのものだけを表示します。こちらもYouTube側の構造に依存するベストエフォートです。"
            "反映には再読み込みが必要です。"
        )
        hide_ui_inner = QVBoxLayout()
        hide_ui_inner.addWidget(self.hide_video_ui_check)
        hide_ui_inner.addWidget(hide_ui_note)
        layout.addWidget(_card(hide_ui_inner))

        self.show_panels_check = QCheckBox(
            "タイトル/ホットキー一覧の欄を表示する"
        )
        self.show_panels_check.setChecked(self.config.get("show_info_panels", default=True))
        panels_note = _subtext(
            "オフにすると動画だけの細いウィンドウになります(ウィンドウ幅の設定は無視されます)。"
        )
        panels_inner = QVBoxLayout()
        panels_inner.addWidget(self.show_panels_check)
        panels_inner.addWidget(panels_note)
        layout.addWidget(_card(panels_inner))

        layout.addStretch(1)
        return _page(layout)

    def _handle_login_click(self):
        # This dialog is shown non-modally (see main.py's open_settings),
        # so the login window it opens here works independently -- no
        # need to close this one first.
        if self._on_login:
            self._on_login()

    # ------------------------------------------------------------- save

    def _save(self):
        hotkey_specs = {}
        for name, widgets in self._hotkey_widgets.items():
            key = widgets["key"].text().strip().upper()
            mods = [m for m in MOD_ORDER if widgets["mods"][m].isChecked()]
            if not key:
                QMessageBox.warning(self, "設定", "ホットキーのキーが未入力の項目があります。")
                return
            hotkey_specs[name] = {"modifiers": mods, "key": key}

        combos = [
            (tuple(sorted(spec["modifiers"])), spec["key"]) for spec in hotkey_specs.values()
        ]
        if len(combos) != len(set(combos)):
            QMessageBox.warning(self, "設定", "ホットキーが重複しています。別の組み合わせにしてください。")
            return

        self.config.set("hotkeys", hotkey_specs)
        self.config.set("compact_style", self.compact_style_check.isChecked())
        self.config.set("hide_video_ui", self.hide_video_ui_check.isChecked())
        self.config.set("show_info_panels", self.show_panels_check.isChecked())
        self.config.set("window", "width", self.width_spin.value())
        self.config.set("window", "height", self.height_spin.value())
        self.config.set("window", "margin_bottom", self.margin_spin.value())
        if self.auto_position_check.isChecked():
            self.config.set("window", "x", None)
            self.config.set("window", "y", None)
        else:
            self.config.set("window", "x", self.x_spin.value())
            self.config.set("window", "y", self.y_spin.value())

        self.config.save()
        self.accept()


def _page(layout):
    widget = QWidget()
    widget.setLayout(layout)
    return widget


def _wrap_label(label):
    layout = QVBoxLayout()
    layout.addWidget(label)
    return layout


def _hotkey_row(description, spec):
    row = QHBoxLayout()
    row.addWidget(QLabel(description), 1)
    mods = "+".join(MOD_LABELS.get(m, m.capitalize()) for m in spec.get("modifiers", []))
    key = spec.get("key", "?")
    badge = QLabel(f"{mods}+{key}" if mods else key)
    badge.setProperty("class", "keyBadge")
    row.addWidget(badge)
    return row
