"""PyQt6 floating overlay window — scrollable + draggable"""

import os
import json
from PyQt6.QtWidgets import (
    QMainWindow, QLabel, QVBoxLayout, QWidget,
    QApplication, QScrollArea,
)
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QCursor


class UIOverlay(QMainWindow):

    def __init__(self):
        super().__init__()

        settings_path = os.path.join(os.path.dirname(__file__), "..", "config", "settings.json")
        with open(settings_path) as f:
            self.settings = json.load(f)

        self.answer_text = ""
        self.transcription_text = ""
        self.is_visible = False
        self._drag_pos = QPoint()

        self._setup_ui()
        self._setup_window()

    def _setup_ui(self):
        central_widget = QWidget(self)
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(6)

        self.transcription_label = QLabel("🎤 Listening...")
        self.transcription_label.setStyleSheet("color: #aaa; font-size: 11px; font-style: italic;")
        self.transcription_label.setWordWrap(True)
        layout.addWidget(self.transcription_label)

        # Scrollable answer area
        self.answer_label = QLabel()
        self.answer_label.setWordWrap(True)
        self.answer_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.answer_label.setStyleSheet("color: #ffffff; font-size: 13px; background: transparent;")
        self.answer_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.answer_label.setMinimumWidth(self.settings["window_width"] - 40)

        scroll = QScrollArea()
        scroll.setWidget(self.answer_label)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical { width: 6px; background: #2e2e3e; }"
            "QScrollBar::handle:vertical { background: #555; border-radius: 3px; }"
        )
        scroll.setMinimumHeight(self.settings["window_height"] - 70)
        layout.addWidget(scroll)

        self.status_label = QLabel("✓ Ready")
        self.status_label.setStyleSheet("color: #4CAF50; font-size: 9px;")
        layout.addWidget(self.status_label)

        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

    def _setup_window(self):
        width = self.settings["window_width"]
        height = self.settings["window_height"]
        self.setGeometry(100, 100, width, height)
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setStyleSheet("background-color: #1e1e2e; border-radius: 10px;")
        self._position_window()
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.hide()

    def _position_window(self):
        pos = self.settings.get("position", {})
        x, y = pos.get("x"), pos.get("y")
        if x is None or y is None:
            screen_geom = QApplication.primaryScreen().geometry()
            x = screen_geom.width() - self.settings["window_width"] - 50
            y = 100
        self.move(x, y)

    # ---------- Drag support ----------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = QPoint()

    # ---------- Public API ----------

    def set_answer(self, text: str):
        self.answer_text = text
        self.answer_label.setText(self._format_answer(text))
        self.answer_label.adjustSize()

    def set_transcription(self, text: str):
        if self.settings.get("show_transcription", True):
            self.transcription_text = text
            self.transcription_label.setText(f"🎤 {text}")

    def _format_answer(self, text: str) -> str:
        lines = text.split("\n")
        formatted = []
        for line in lines:
            s = line.strip()
            if s.startswith("-") or s.startswith("*"):
                formatted.append(f"  • {s[1:].strip()}")
            elif s.endswith(":"):
                formatted.append(f"<b>{line}</b>")
            else:
                formatted.append(line)
        return "\n".join(formatted)

    def toggle_visibility(self):
        if self.is_visible:
            self.hide()
            self.is_visible = False
        else:
            self.show()
            self.is_visible = True

    def show_answer(self, text: str):
        self.set_answer(text)
        if not self.is_visible:
            self.toggle_visibility()

    def hide_answer(self):
        if self.is_visible:
            self.toggle_visibility()

    def update_status(self, status: str):
        self.status_label.setText(status)

    def closeEvent(self, event):
        self.hide()
        self.is_visible = False
        event.ignore()
