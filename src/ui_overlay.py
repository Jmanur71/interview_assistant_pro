"""PyQt6 floating overlay — all output inside window, screen-capture toggle via Ctrl+H"""

import os
import sys
import json
import ctypes

def _base_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.join(os.path.dirname(__file__), "..")
from PyQt6.QtWidgets import (
    QMainWindow, QLabel, QVBoxLayout, QHBoxLayout,
    QWidget, QApplication, QPushButton, QTextEdit,
)
from PyQt6.QtCore import Qt, QPoint, QDateTime
from PyQt6.QtGui import QCursor, QTextCursor
from typing import Optional, Callable

_user32 = ctypes.windll.user32
WDA_NONE               = 0x00000000   # visible to screen capture
WDA_EXCLUDEFROMCAPTURE = 0x00000011   # hidden from screen capture


class UIOverlay(QMainWindow):

    def __init__(self):
        super().__init__()

        settings_path = os.path.join(_base_dir(), "config", "settings.json")
        with open(settings_path) as f:
            self.settings = json.load(f)

        self.answer_text = ""
        self.transcription_text = ""
        self._hidden_from_capture = True
        self._drag_pos = QPoint()
        self.on_mode_change: Optional[Callable] = None
        self.on_close: Optional[Callable] = None

        self._setup_window()
        self._setup_ui()
        self._position_window()
        self.show()
        self._apply_capture_affinity(hidden=True)

    # ── window chrome ──────────────────────────────────────────────────────────

    def _setup_window(self):
        w = self.settings["window_width"]
        h = self.settings["window_height"]
        self.setFixedWidth(w)
        self.setMinimumHeight(h)
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def _setup_ui(self):
        root = QWidget(self)
        root.setObjectName("root")
        root.setStyleSheet("""
            QWidget#root {
                background-color: rgba(13, 13, 23, 242);
                border: 1px solid #3a3a5c;
                border-radius: 12px;
            }
        """)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── title bar ──
        title_bar = QWidget()
        title_bar.setStyleSheet("background: rgba(25,25,45,220); border-radius: 12px 12px 0 0;")
        title_bar.setFixedHeight(34)
        tb = QHBoxLayout(title_bar)
        tb.setContentsMargins(12, 0, 8, 0)

        title_lbl = QLabel("🎯 Interview Assistant")
        title_lbl.setStyleSheet("color: #8be9fd; font-size: 12px; font-weight: bold;")
        tb.addWidget(title_lbl)
        tb.addStretch()

        # capture-state indicator
        self._capture_indicator = QLabel("👁 Hidden from interviewer")
        self._capture_indicator.setStyleSheet("color: #50fa7b; font-size: 9px;")
        tb.addWidget(self._capture_indicator)
        tb.addSpacing(8)

        # audio mode buttons
        self._mode_buttons: dict[str, QPushButton] = {}
        for mode, label, tip in [
            ("speaker", "🔊", "Speaker only"),
            ("both",    "🔀", "Speaker + Mic"),
            ("mic",     "🎤", "Mic only"),
        ]:
            btn = QPushButton(label)
            btn.setFixedSize(28, 22)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setStyleSheet(self._mode_btn_style(False))
            btn.clicked.connect(lambda _checked, m=mode: self._on_mode_btn(m))
            tb.addWidget(btn)
            self._mode_buttons[mode] = btn
        self._set_active_mode_btn("mic")

        tb.addSpacing(6)
        self.status_label = QLabel("● Starting...")
        self.status_label.setStyleSheet("color: #ffb86c; font-size: 10px;")
        tb.addWidget(self.status_label)

        # ── macOS traffic light buttons ──
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(16, 16)
        close_btn.setToolTip("Quit")
        close_btn.setStyleSheet(
            "QPushButton{background:#ff5f56;color:rgba(0,0,0,0);border-radius:8px;font-size:9px;font-weight:bold;border:none;}"
            "QPushButton:hover{background:#ff3b30;color:rgba(0,0,0,180);}"
        )
        close_btn.clicked.connect(lambda: self.on_close() if self.on_close else QApplication.instance().quit())
        tb.addWidget(close_btn)

        min_btn = QPushButton("–")
        min_btn.setFixedSize(16, 16)
        min_btn.setToolTip("Minimise")
        min_btn.setStyleSheet(
            "QPushButton{background:#ffbd2e;color:rgba(0,0,0,0);border-radius:8px;font-size:9px;font-weight:bold;border:none;}"
            "QPushButton:hover{background:#e6a800;color:rgba(0,0,0,180);}"
        )
        min_btn.clicked.connect(self.showMinimized)
        tb.addWidget(min_btn)

        max_btn = QPushButton("⤢")
        max_btn.setFixedSize(16, 16)
        max_btn.setToolTip("Maximise")
        max_btn.setStyleSheet(
            "QPushButton{background:#27c93f;color:rgba(0,0,0,0);border-radius:8px;font-size:9px;font-weight:bold;border:none;}"
            "QPushButton:hover{background:#1aab2e;color:rgba(0,0,0,180);}"
        )
        max_btn.clicked.connect(self._toggle_maximize)
        tb.addWidget(max_btn)
        tb.addSpacing(4)

        outer.addWidget(title_bar)

        # ── content ──
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(12, 8, 12, 6)
        cl.setSpacing(4)

        # question label
        self.transcription_label = QLabel("🎤 Waiting for audio...")
        self.transcription_label.setStyleSheet(
            "color: #6272a4; font-size: 11px; font-style: italic;"
        )
        self.transcription_label.setWordWrap(True)
        cl.addWidget(self.transcription_label)

        # answer — QTextEdit handles HTML + scrolling natively
        self.answer_box = QTextEdit()
        self.answer_box.setReadOnly(True)
        self.answer_box.setMinimumHeight(self.settings["window_height"] - 200)
        self.answer_box.setStyleSheet(
            "QTextEdit{color:#f8f8f2;font-size:13px;background:rgba(0,0,0,0);"
            "border:none;padding:4px;}"
            "QScrollBar:vertical{width:5px;background:transparent;}"
            "QScrollBar::handle:vertical{background:#44475a;border-radius:2px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )
        self.answer_box.setHtml("<span style='color:#6272a4;'>Answer will appear here...</span>")
        cl.addWidget(self.answer_box)

        # log panel — replaces terminal output
        log_sep = QLabel("── Log ──────────────────────────────────────────")
        log_sep.setStyleSheet("color: #44475a; font-size: 9px;")
        cl.addWidget(log_sep)

        self._log_box = QTextEdit()
        self._log_box.setReadOnly(True)
        self._log_box.setFixedHeight(110)
        self._log_box.setStyleSheet(
            "QTextEdit{background:rgba(0,0,0,80);color:#6272a4;"
            "font-size:10px;font-family:Consolas,monospace;"
            "border:none;border-radius:4px;padding:4px;}"
        )
        cl.addWidget(self._log_box)

        # hint
        hint = QLabel("Ctrl+H toggle capture-hide  •  Ctrl+C copy  •  Ctrl+V pause/resume voice")
        hint.setStyleSheet("color: #44475a; font-size: 9px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(hint)

        outer.addWidget(content)

        container = QWidget()
        QVBoxLayout(container).addWidget(root)
        container.layout().setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(container)

    def _position_window(self):
        pos = self.settings.get("position", {})
        x, y = pos.get("x"), pos.get("y")
        if x is None or y is None:
            g = QApplication.primaryScreen().geometry()
            x = g.width() - self.settings["window_width"] - 20
            y = 60
        self.move(x, y)

    # ── capture affinity ───────────────────────────────────────────────────────

    def _apply_capture_affinity(self, hidden: bool):
        try:
            affinity = WDA_EXCLUDEFROMCAPTURE if hidden else WDA_NONE
            _user32.SetWindowDisplayAffinity(int(self.winId()), affinity)
        except Exception:
            pass
        self._hidden_from_capture = hidden
        if hidden:
            self._capture_indicator.setText("👁 Hidden from interviewer")
            self._capture_indicator.setStyleSheet("color: #50fa7b; font-size: 9px;")
        else:
            self._capture_indicator.setText("⚠ Visible to interviewer")
            self._capture_indicator.setStyleSheet("color: #ff5555; font-size: 9px;")

    def toggle_capture_hide(self):
        """Ctrl+H: toggle whether interviewer's screen capture can see this window."""
        self._apply_capture_affinity(not self._hidden_from_capture)

    # ── drag ──────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = QPoint()

    # ── public API ────────────────────────────────────────────────────────────

    def log(self, msg: str):
        """Route all status/debug output here instead of terminal."""
        ts = QDateTime.currentDateTime().toString("hh:mm:ss")
        self._log_box.append(f"<span style='color:#44475a;'>[{ts}]</span> {msg}")
        self._log_box.moveCursor(QTextCursor.MoveOperation.End)

    def set_transcription(self, text: str):
        if self.settings.get("show_transcription", True):
            self.transcription_text = text
            self.transcription_label.setText(f"❓ {text}")

    def set_answer(self, text: str):
        self.answer_text = text
        self.answer_box.clear()
        self.answer_box.setHtml(self._format_answer(text))
        self.answer_box.verticalScrollBar().setValue(0)

    def show_answer(self, text: str):
        self.set_answer(text)

    def _format_answer(self, text: str) -> str:
        import re
        lines = text.split("\n")
        out = []
        for line in lines:
            s = line.strip()
            if not s:
                out.append("")
            elif s.startswith("* ") or s.startswith("- "):
                out.append(f"&nbsp;&nbsp;<span style='color:#50fa7b;'>&#9679;</span> {s[2:].strip()}")
            elif s.startswith("**") and s.endswith("**"):
                out.append(f"<b style='color:#8be9fd;'>{s[2:-2]}</b>")
            elif s.startswith("**") and ":**" in s:
                label, rest = s.split(":**", 1)
                out.append(f"<b style='color:#8be9fd;'>{label[2:]}:</b> {rest.strip()}")
            elif re.match(r'^\*\*(.+):\*\*', s):
                s2 = re.sub(r'^\*\*(.+):\*\*', r"<b style='color:#8be9fd;'>\1:</b>", s)
                out.append(s2)
            else:
                out.append(s)
        return "<br>".join(out)

    def update_status(self, status: str):
        color = (
            "#50fa7b" if ("ready" in status.lower() or "✓" in status) else
            "#ff5555" if ("error" in status.lower() or "❌" in status) else
            "#ffb86c"
        )
        self.status_label.setText(f"● {status}")
        self.status_label.setStyleSheet(f"color: {color}; font-size: 10px;")

    @staticmethod
    def _mode_btn_style(active: bool) -> str:
        if active:
            return ("QPushButton{background:#6272a4;color:white;border-radius:4px;"
                    "font-size:12px;border:none;padding:0 2px;}")
        return ("QPushButton{background:#2e2e4e;color:#888;border-radius:4px;"
                "font-size:12px;border:none;padding:0 2px;}"
                "QPushButton:hover{background:#44475a;color:white;}")

    def _set_active_mode_btn(self, mode: str):
        for m, btn in self._mode_buttons.items():
            btn.setChecked(m == mode)
            btn.setStyleSheet(self._mode_btn_style(m == mode))

    def _on_mode_btn(self, mode: str):
        self._set_active_mode_btn(mode)
        self.update_status(f"Switching to {mode}...")
        if self.on_mode_change:
            self.on_mode_change(mode)

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def closeEvent(self, event):
        event.ignore()  # X on taskbar does nothing; only red button quits via app.quit()
