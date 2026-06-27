"""Interview Assistant Pro - Main Application"""

import asyncio
import sys
import os

# Force UTF-8 stdout/stderr on Windows (fixes emoji/unicode in print())
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import json
import threading

# ── Suppress terminal output after startup ────────────────────────────────────
import io
_null = open(os.devnull, "w", encoding="utf-8", errors="replace")
import atexit
atexit.register(_null.close)

def _silence_terminal():
    sys.stdout = _null
    sys.stderr = _null

# ── Qt + local imports ───────────────────────────────────────────────────────
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, pyqtSignal, QObject, Qt


class _Bridge(QObject):
    """Thread-safe bridge: emit call_signal from any thread, slot runs on Qt main thread."""
    call_signal = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.call_signal.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def _run(self, func):
        func()

    def post(self, func):
        self.call_signal.emit(func)

# ── Frozen-exe path helper ───────────────────────────────────────────────────
def _base_dir() -> str:
    """Root dir: works both when run as .py and as a PyInstaller .exe."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.join(os.path.dirname(__file__), "..")

from audio_processor import AudioProcessor
from openai_client import OpenAIRealtimeClient
from ui_overlay import UIOverlay
from hotkey_manager import HotkeyManager
from screen_share_detector import ScreenShareDetector
from token_storage import load_token


class InterviewAssistant:

    def __init__(self, loop: asyncio.AbstractEventLoop, app: QApplication):
        self.loop = loop
        self.app = app
        self._bridge = _Bridge()

        self._load_settings()

        self.audio = AudioProcessor(
            mode=self.settings.get("audio_mode", "mic"),
            threshold=self.settings.get("voice_activation_threshold", 0.04),
            silence_seconds=self.settings.get("silence_duration", 2.0),
        )
        self.audio.loop = self.loop

        self.openai = OpenAIRealtimeClient()
        self.ui = UIOverlay()
        self.hotkeys = HotkeyManager()
        self.screen_detector = ScreenShareDetector()
        self.current_question = ""

        self._setup()

    def _load_settings(self):
        path = os.path.join(_base_dir(), "config", "settings.json")
        with open(path) as f:
            self.settings = json.load(f)

    def _setup(self):
        token = load_token()
        if not token:
            self.ui.log("❌ No API token found. Run: python src/setup.py")
            sys.exit(1)

        self.ui.log("✓ API token configured")

        self.audio.on_audio_chunk  = self._on_audio_chunk
        self.audio.on_voice_start  = self._on_voice_start
        self.audio.on_voice_end    = self._on_voice_end

        self.openai.on_transcription = self._on_transcription
        self.openai.on_answer        = self._on_answer
        self.openai.on_error         = self._on_api_error

        self.ui.on_mode_change = self._on_mode_change
        self.ui.on_close = self.shutdown
        # Wire resume upload callback
        self.ui.on_resume_upload = self._on_resume_upload

        self.hotkeys.register_hotkeys({
            "toggle_visibility":   self._toggle_capture_hide,
            "copy_answer":         self._copy_answer,
            "toggle_voice_input":  self._toggle_voice_input,
            "toggle_dashboard":    self._toggle_dashboard,
            "restore_window":      self._restore_window,
        })

        self.ui.log("✓ All systems initialized")

    # ── UI thread helper ──────────────────────────────────────────────────────

    def _ui_call(self, func):
        self._bridge.post(func)

    # ── Audio / AI callbacks ──────────────────────────────────────────────────

    async def _on_audio_chunk(self, audio_base64: str):
        await self.openai.send_audio(audio_base64)

    async def _on_voice_start(self):
        self._ui_call(lambda: self.ui.update_status("🎤 Listening..."))
        self._ui_call(lambda: self.ui.log("🔴 Voice detected — recording"))

    async def _on_voice_end(self):
        if self.openai._processing:
            self._ui_call(lambda: self.ui.update_status("⏳ Still processing previous..."))
            self._ui_call(lambda: self.ui.log("⏭ Skipped — previous answer still processing"))
            return
        else:
            self._ui_call(lambda: self.ui.update_status("⏳ Processing..."))
            self._ui_call(lambda: self.ui.log("⏹ Voice ended — sending to AI"))
            await self.openai.send_turn_end()

    async def _on_transcription(self, text: str):
        self.current_question = text
        self._ui_call(lambda: self.ui.set_transcription(text))
        self._ui_call(lambda: self.ui.log(f"❓ <b>{text}</b>"))

    async def _on_answer(self, answer: list):
        text = ""
        for item in answer:
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "text":
                        text = c.get("text", "")
        if text:
            t = text  # explicit capture for lambdas
            self._ui_call(lambda: self.ui.show_answer(t))
            self._ui_call(lambda: self.ui.update_status("✓ Answer ready"))
            self._ui_call(lambda: self.ui.log("💡 Answer updated"))

    async def _on_api_error(self, error: str):
        # Parse retry wait time from 429 message e.g. "try again in 2m15.648s"
        import re
        wait_match = re.search(r"try again in (\d+)m([\d.]+)s", error)
        if not wait_match:
            wait_match = re.search(r"try again in ([\d.]+)s", error)
            wait_secs = int(float(wait_match.group(1))) + 1 if wait_match else None
        else:
            wait_secs = int(wait_match.group(1)) * 60 + int(float(wait_match.group(2))) + 1

        if wait_secs:
            self._ui_call(lambda: self.ui.log(f"⚠️ Rate limited — retrying in {wait_secs}s"))
            self._ui_call(lambda: self.ui.update_status(f"⏳ Rate limit — wait {wait_secs}s"))
        else:
            self._ui_call(lambda: self.ui.log(f"❌ API error: {error[:120]}"))
            self._ui_call(lambda: self.ui.update_status("❌ API error"))

    # ── Hotkey handlers ───────────────────────────────────────────────────────

    def _toggle_capture_hide(self):
        """Ctrl+H — toggle screen-capture invisibility. Window stays visible to you."""
        self._ui_call(self.ui.toggle_capture_hide)

    def _copy_answer(self):
        if not self.ui.answer_text:
            return
        def _do():
            QApplication.clipboard().setText(self.ui.answer_text)
            self.ui.update_status("✓ Copied")
            self.ui.log("📋 Answer copied to clipboard")
        self._ui_call(_do)

    def _toggle_voice_input(self):
        if self.audio.is_running:
            asyncio.run_coroutine_threadsafe(self.audio.stop(), self.loop)
            self._ui_call(lambda: self.ui.update_status("🔇 Voice paused"))
            self._ui_call(lambda: self.ui.log("🔇 Voice capture paused"))
        else:
            asyncio.run_coroutine_threadsafe(self.audio.start(), self.loop)
            self._ui_call(lambda: self.ui.update_status("🎤 Voice resumed"))
            self._ui_call(lambda: self.ui.log("🎤 Voice capture resumed"))

    def _on_mode_change(self, mode: str):
        async def _switch():
            await self.audio.set_mode(mode)
            self.openai._capture_sample_rate = self.audio.capture_sample_rate
            self.openai._capture_channels    = self.audio.capture_channels
            self._ui_call(lambda: self.ui.update_status(f"✓ {mode.capitalize()} mode"))
            self._ui_call(lambda: self.ui.log(f"🔄 Audio mode → {mode}"))
        asyncio.run_coroutine_threadsafe(_switch(), self.loop)

    def _toggle_dashboard(self):
        self._ui_call(lambda: self.ui.update_status("⚙ Dashboard (coming soon)"))

    def _restore_window(self):
        """Ctrl+M — collapse/expand toggle. Always brings the window back."""
        self._ui_call(self.ui.toggle_collapse)

    async def _on_screen_share_change(self, is_sharing: bool):
        if is_sharing:
            # already hidden via WDA_EXCLUDEFROMCAPTURE — just log it
            self._ui_call(lambda: self.ui.log("🙈 Screen sharing detected"))
        else:
            self._ui_call(lambda: self.ui.log("✓ Screen sharing ended"))

    def shutdown(self):
        """Stop all background resources then force-exit the process."""
        self.hotkeys.unregister_hotkeys()
        asyncio.run_coroutine_threadsafe(self.audio.stop(), self.loop).result(timeout=2)
        self.loop.call_soon_threadsafe(self.loop.stop)
        os._exit(0)

    # ── Resume upload handler ─────────────────────────────────────────────────

    def _on_resume_upload(self, text: str, filename: str):
        # Store resume text in OpenAI client for context. Truncate to 3000 chars to avoid huge payloads.
        try:
            truncated = text[:3000]
            self.openai.resume_text = truncated
            self.ui.log(f"✓ Resume registered: {filename} ({len(truncated)} chars sent to context)")
        except Exception as e:
            self.ui.log(f"❌ Failed to register resume: {e}")

    # ── Main run ───────────────────────────────────────────────────────────�[...] 

    async def run(self):
        try:
            self._ui_call(lambda: self.ui.log("⏳ Connecting to Groq..."))
            await self.openai.connect()
            self._ui_call(lambda: self.ui.log("✓ Groq ready (Whisper + LLaMA)"))

            # Use the optimized system prompt (already set in openai_client.py)
            # Don't override it

            await self.audio.start()
            self.openai._capture_sample_rate = self.audio.capture_sample_rate
            self.openai._capture_channels    = self.audio.capture_channels
            self._ui_call(lambda: self.ui.log("✓ Audio capture started"))
            self._ui_call(lambda: self.ui.update_status("✓ Ready — speak your question"))

            asyncio.create_task(
                self.screen_detector.monitor(self._on_screen_share_change)
            )

            self._ui_call(lambda: self.ui.log(
                "✅ Interview Assistant ready — Ctrl+H toggles interviewer visibility"
            ))

            while True:
                await asyncio.sleep(1)

        except Exception as e:
            import traceback
            self._ui_call(lambda: self.ui.log(f"❌ Startup error: {e}"))
            self._ui_call(lambda: self.ui.update_status(f"❌ Error: {e}"))
            raise


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None
    sys.stderr.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stderr, "reconfigure") else None
    print("Interview Assistant Pro -- starting")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Create event loop in main thread (before async thread)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Background thread for async operations
    t = threading.Thread(
        target=loop.run_forever,
        daemon=False,
        name="AsyncEventLoop"
    )

    assistant = None
    future = None
    
    try:
        t.start()
        print("✓ Event loop started in background thread")
        
        # Give thread time to initialize
        import time
        time.sleep(0.1)
        
        assistant = InterviewAssistant(loop, app)
        future = asyncio.run_coroutine_threadsafe(assistant.run(), loop)

        def check_error():
            try:
                if future and future.done():
                    exc = future.exception()
                    if exc:
                        try:
                            assistant.ui.log(f"❌ Fatal: {exc}")
                            assistant.ui.update_status(f"❌ {exc}")
                        except Exception:
                            pass
                        # Give user 10s to read the error before quitting
                        QTimer.singleShot(10000, app.quit)
            except Exception as e:
                print(f"Error in check_error: {e}", file=sys.stderr)

        timer = QTimer()
        timer.timeout.connect(check_error)
        timer.start(1000)

        # Keep Qt app running
        exit_code = app.exec()
        print("✓ Qt application closed")
        return exit_code
        
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        sys.stderr = sys.__stderr__
        print(err, file=sys.stderr)
        try:
            if assistant and assistant.ui:
                assistant.ui.log(f"❌ Failed to start: {e}")
        except Exception:
            pass
        return 1
    finally:
        # Graceful cleanup
        print("Shutting down...")
        try:
            if future:
                future.cancel()
        except Exception:
            pass
        
        # Stop the event loop safely
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
        
        # Wait for thread to finish (max 3 seconds)
        t.join(timeout=3)
        
        # Close event loop
        try:
            if not loop.is_closed():
                loop.close()
        except Exception:
            pass
        
        print("✓ Cleanup complete")
        sys.exit(0)


if __name__ == "__main__":
    main()
