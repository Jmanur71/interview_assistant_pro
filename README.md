# 🎯 Interview Assistant Pro

A real-time AI-powered interview assistant that listens to spoken questions via your microphone, transcribes them using **Whisper**, generates structured answers using **LLaMA 3.3**, and displays them in a floating overlay window — all while staying invisible during screen sharing.

---

## ✨ Features

- 🎤 **Voice-activated listening** — automatically detects when you start and stop speaking
- 📝 **Whisper transcription** — powered by `whisper-large-v3` via Groq API
- 🤖 **LLaMA 3.3 answers** — structured responses with bullet points and examples
- 🪟 **Floating overlay** — always-on-top, draggable, frameless PyQt6 window
- 🙈 **Screen share detection** — auto-hides the overlay when Zoom, Teams, etc. are detected
- 🔒 **Secure token storage** — API key stored in system keyring, falls back to `.env`
- ⌨️ **Global hotkeys** — control the assistant without switching windows
- 💬 **Conversation history** — maintains last 10 exchanges for contextual answers
- 🔁 **Auto-retry on rate limits** — handles Groq 429 errors with backoff
- 🖥️ **Rich terminal output** — clean formatted panels for questions and answers

---

## 🏗️ Architecture

```
interview_assistant_pro/
├── src/
│   ├── main.py                 # App controller, wires all components together
│   ├── audio_processor.py      # Mic capture, VAD (voice activity detection)
│   ├── openai_client.py        # Groq API: Whisper transcription + LLaMA answers
│   ├── ui_overlay.py           # PyQt6 floating overlay window
│   ├── hotkey_manager.py       # Global hotkey registration via pynput
│   ├── screen_share_detector.py# Detects sharing apps via psutil
│   ├── token_storage.py        # Keyring + .env token management
│   └── setup.py                # First-run setup wizard
├── config/
│   ├── settings.json           # Window, audio, and display settings
│   ├── hotkeys.json            # Configurable hotkey bindings
│   ├── .env                    # Fallback API token storage
│   └── .env.example            # Template for manual token setup
├── requirements.txt
└── restart.bat                 # Windows quick-restart script
```

### Flow

```
Microphone → AudioProcessor (VAD)
               ↓ voice detected
           OpenAIRealtimeClient
               ↓ Whisper (transcription)
               ↓ LLaMA 3.3 (answer generation)
               ↓
        UIOverlay (floating window)  +  Rich terminal panels
```

---

## 🛠️ Requirements

- Python 3.9+
- Windows (primary support; macOS/Linux compatible with minor adjustments)
- A [Groq API key](https://console.groq.com/keys) (free tier available)
- A working microphone

---

## 🚀 Quick Start

### 1. Clone and navigate
```bash
git clone <repo-url>
cd interview_assistant_pro
```

### 2. Create virtual environment
```bash
python -m venv venv
```

### 3. Activate virtual environment

**Windows (PowerShell):**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
venv\Scripts\activate
```

**Windows (CMD):**
```cmd
venv\Scripts\activate.bat
```

**macOS / Linux:**
```bash
source venv/bin/activate
```

### 4. Run setup
```bash
python src/setup.py
```
This will:
- Install all dependencies from `requirements.txt`
- Prompt you to enter your Groq API key
- Save it securely to the system keyring (falls back to `config/.env`)

### 5. Start the assistant
```bash
python src/main.py
```

Or use the Windows quick-restart script:
```bat
.\restart.bat
```

---

## ⌨️ Hotkeys

| Hotkey | Action |
|--------|--------|
| `Ctrl + H` | Toggle overlay visibility |
| `Ctrl + C` | Copy current answer to clipboard |
| `Ctrl + V` | Toggle voice input on/off |
| `Ctrl + D` | Toggle dashboard (future feature) |

Hotkeys are configurable in `config/hotkeys.json`.

---

## 🖥️ Terminal Output

Once running, the terminal shows clean Rich-formatted output:

```
╭─────────────────────────────────────╮
│ 🎯 Interview Assistant Pro Starting │
╰─────────────────────────────────────╯
✓ API token configured
✓ Groq client ready (Whisper + LLaMA)
✓ Audio capture started
╭─────────────────────────────────────╮
│ ✓ Interview Assistant is ready!     │
│ Ctrl+H toggle  Ctrl+C copy ...      │
╰─────────────────────────────────────╯

🔴 Voice detected — recording started
⏹️  Voice ended — sending to AI

╭─ ❓ Question ───────────────────────╮
│ Tell me about yourself.             │
╰─────────────────────────────────────╯

╭─ 💡 Answer ────────────────────────╮
│ Main answer here...                 │
│                                     │
│  • Bullet point 1                   │
│  • Bullet point 2                   │
╰─────────────────────────────────────╯
```

---

## ⚙️ Configuration

### `config/settings.json`

| Key | Default | Description |
|-----|---------|-------------|
| `window_width` | `520` | Overlay window width in pixels |
| `window_height` | `420` | Overlay window height in pixels |
| `show_transcription` | `true` | Show question text in overlay |
| `voice_activation_threshold` | `0.04` | Mic volume threshold to trigger recording |
| `silence_duration` | `2.0` | Seconds of silence before ending recording |
| `alpha` | `0.95` | Window opacity (0.0–1.0) |
| `position.x / y` | `null` | Override window position (null = auto top-right) |

### `config/hotkeys.json`

```json
{
  "toggle_visibility": "<ctrl>+h",
  "copy_answer": "<ctrl>+c",
  "toggle_voice_input": "<ctrl>+v",
  "toggle_dashboard": "<ctrl>+d"
}
```

Modify any hotkey using [pynput key format](https://pynput.readthedocs.io/en/latest/keyboard.html#pynput.keyboard.Key).

---

## 🔑 API Token Management

The token is stored using this priority order:

1. **System keyring** (most secure — Windows Credential Manager / macOS Keychain)
2. **`config/.env`** file (fallback if keyring is unavailable)

To update your token, re-run:
```bash
python src/setup.py
```

To set the token manually via `.env`:
```env
# config/.env
OPENAI_API_TOKEN=your_groq_api_key_here
```

---

## 🙈 Screen Share Detection

The assistant automatically monitors for these applications and hides the overlay when detected:

- Zoom
- Microsoft Teams
- Webex
- GoToMeeting
- AnyDesk
- TeamViewer

Detection runs every 5 seconds via `psutil` process scanning (no subprocess calls).

---

## 📦 Dependencies

| Package | Purpose |
|---------|---------|
| `pyqt6` | Floating overlay UI |
| `pynput` | Global hotkey capture |
| `sounddevice` | Microphone audio capture |
| `numpy` | Audio data processing |
| `groq` | Whisper + LLaMA API client |
| `keyring` | Secure token storage |
| `python-dotenv` | `.env` file loading |
| `psutil` | Screen share detection |
| `rich` | Formatted terminal output |

---

## 🔧 Troubleshooting

**No audio captured / not detecting voice:**
- Check your default microphone is set correctly in Windows Sound Settings
- Adjust `voice_activation_threshold` in `settings.json` (lower = more sensitive, e.g. `0.02`)

**`❌ No API token found`:**
- Run `python src/setup.py` to configure your Groq API key

**Rate limit warnings (`⚠️ Rate limited`):**
- The app auto-retries up to 3 times with backoff
- Upgrade your Groq plan or wait for the rate limit window to reset

**Overlay not appearing:**
- Press `Ctrl+H` to toggle visibility
- The overlay only shows after the first answer is received

**`venv\Scripts\activate` not working in PowerShell:**
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

---

## 🔐 Stability & Resource Management

The event loop in `main.py` is wrapped in a single `try/finally` block, guaranteeing `loop.close()` is always called on every exit path — normal shutdown, startup failure, or unhandled exception. This prevents resource leaks regardless of how the app terminates.

---

## 📄 License

MIT License — free for personal and commercial use.
