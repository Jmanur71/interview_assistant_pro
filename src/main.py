"""Interview Assistant Pro - Main Application"""

import asyncio
import sys
import json
import os
import threading
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich import print as rprint

console = Console()

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from audio_processor import AudioProcessor
from openai_client import OpenAIRealtimeClient
from ui_overlay import UIOverlay
from hotkey_manager import HotkeyManager
from screen_share_detector import ScreenShareDetector
from token_storage import load_token


class InterviewAssistant:
    """Main application controller"""

    def __init__(self, loop: asyncio.AbstractEventLoop, app: QApplication):
        self.loop = loop
        self.app = app

        self.audio = AudioProcessor()
        # give audio the loop so it can schedule callbacks
        self.audio.loop = self.loop

        self.openai = OpenAIRealtimeClient()
        self.ui = UIOverlay()
        self.hotkeys = HotkeyManager()
        self.screen_detector = ScreenShareDetector()

        self.is_voice_active = False
        self.current_question = ""

        self._load_settings()
        self._setup()

    def _load_settings(self):
        """Load application settings"""
        settings_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "settings.json"
        )
        with open(settings_path) as f:
            self.settings = json.load(f)

    def _setup(self):
        """Initialize application"""
        console.print(Panel("🎯 [bold cyan]Interview Assistant Pro[/bold cyan] Starting...", border_style="cyan"))

        # Verify API token
        token = load_token()
        if not token:
            console.print("[red]❌ No API token found. Run: python src/setup.py[/red]")
            sys.exit(1)

        console.print("[green]✓[/green] API token configured")

        # Setup audio callbacks
        self.audio.on_audio_chunk = self._on_audio_chunk
        self.audio.on_voice_start = self._on_voice_start
        self.audio.on_voice_end = self._on_voice_end

        # Setup OpenAI callbacks
        self.openai.on_transcription = self._on_transcription
        self.openai.on_answer = self._on_answer

        # UI callbacks → hotkeys
        self.ui_callbacks = {
            "toggle_visibility": self._toggle_visibility,
            "copy_answer": self._copy_answer,
            "toggle_voice_input": self._toggle_voice_input,
            "toggle_dashboard": self._toggle_dashboard,
        }

        self.hotkeys.register_hotkeys(self.ui_callbacks)

        console.print("[green]✓[/green] All systems initialized")

    # ---------- Safe UI helper ----------

    def _ui_call(self, func):
        """Run a function on the Qt GUI thread."""
        QTimer.singleShot(0, func)

    # ---------- Async callbacks (from audio / OpenAI) ----------

    async def _on_audio_chunk(self, audio_base64: str):
        if self.is_voice_active:
            await self.openai.send_audio(audio_base64)

    async def _on_voice_start(self):
        self.is_voice_active = True
        self._ui_call(lambda: self.ui.update_status("🎤 Listening..."))
        console.print("[yellow]🎤 Voice started[/yellow]")

    async def _on_voice_end(self):
        self.is_voice_active = False
        self._ui_call(lambda: self.ui.update_status("⏳ Processing..."))
        console.print("[yellow]🎤 Voice ended[/yellow] → sending to AI")
        await self.openai.send_turn_end()

    async def _on_transcription(self, transcription: str):
        self.current_question = transcription
        self._ui_call(lambda: self.ui.set_transcription(transcription))
        console.print(Panel(f"[bold yellow]❓ Question[/bold yellow]\n{transcription}", border_style="yellow"))

    async def _on_answer(self, answer: list):
        text = ""
        for item in answer:
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "text":
                        text = content.get("text", "")

        if text:
            self._ui_call(lambda: self.ui.show_answer(text))
            self._ui_call(lambda: self.ui.update_status("✓ Answer ready"))
            console.print(Panel(Markdown(text), title="[bold green]💡 Answer[/bold green]", border_style="green"))

    # ---------- Hotkey handlers (called on GUI thread) ----------

    def _toggle_visibility(self):
        self.ui.toggle_visibility()

    def _copy_answer(self):
        if not self.ui.answer_text:
            return

        def do_copy():
            clipboard = QApplication.clipboard()
            clipboard.setText(self.ui.answer_text)
            self.ui.update_status("✓ Copied to clipboard")

        self._ui_call(do_copy)

    def _toggle_voice_input(self):
        if self.is_voice_active:
            # Stop capture
            asyncio.run_coroutine_threadsafe(self.audio.stop(), self.loop)
            self.is_voice_active = False
            self._ui_call(lambda: self.ui.update_status("🔇 Voice disabled"))
        else:
            # Start capture
            asyncio.run_coroutine_threadsafe(self.audio.start(), self.loop)
            self.is_voice_active = True
            self._ui_call(lambda: self.ui.update_status("🎤 Voice enabled"))

    def _toggle_dashboard(self):
        self._ui_call(lambda: self.ui.update_status("⚙️ Dashboard (not implemented)"))

    async def _on_screen_share_change(self, is_sharing: bool):
        if is_sharing:
            self._ui_call(self.ui.hide_answer)
            self._ui_call(lambda: self.ui.update_status("🙈 Screen sharing - hidden"))
            print("🙈 Screen sharing detected - hiding UI")
        else:
            self._ui_call(lambda: self.ui.update_status("✓ Ready"))

    # ---------- Main async logic ----------

    async def run(self):
        await self.openai.connect()

        await self.openai.update_session(
            {
                "modalities": ["text"],
                "voice": "alloy",
                "input_audio_transcription": {"model": "whisper-1"},
                "instructions": """You are an interview assistant. Always respond in English only, regardless of the language of the question.
When the user asks an interview question, provide:
1. A concise main answer (2–3 sentences)
2. 3–5 key talking points with bullet points
3. One compelling insight or example

Keep total response under 150 words. Be professional but conversational.""",
            }
        )

        await self.audio.start()

        # Screen sharing monitor in background
        asyncio.create_task(self.screen_detector.monitor(self._on_screen_share_change))

        console.print(Panel(
            "[green]✓ Interview Assistant is ready![/green]\n"
            "[dim]Ctrl+H[/dim] toggle  [dim]Ctrl+C[/dim] copy  [dim]Ctrl+V[/dim] voice  [dim]Ctrl+D[/dim] dashboard",
            border_style="green"
        ))

        while True:
            await asyncio.sleep(1)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    loop = asyncio.new_event_loop()

    def loop_runner():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    t = threading.Thread(target=loop_runner, daemon=True)
    try:
        t.start()
    except RuntimeError as e:
        print(f"❌ Failed to start event loop thread: {e}")
        loop.close()
        sys.exit(1)

    assistant = InterviewAssistant(loop, app)
    future = asyncio.run_coroutine_threadsafe(assistant.run(), loop)

    def check_error():
        if future.done() and future.exception():
            console.print(f"[red]❌ Fatal error:[/red] {future.exception()}")
            app.quit()

    error_timer = QTimer()
    error_timer.timeout.connect(check_error)
    error_timer.start(1000)

    try:
        sys.exit(app.exec())
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=3)
        loop.close()


if __name__ == "__main__":
    main()