"""Low-latency audio capture and preprocessing"""

import numpy as np
import sounddevice as sd
import asyncio
import base64
from typing import Callable, Optional


class AudioProcessor:
    """Capture microphone audio with <500ms latency"""

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_size: int = 4096,
        threshold: float = 0.04,
        silence_seconds: float = 2.0,
        min_speech_chunks: int = 2,
    ):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.threshold = threshold
        self.silence_seconds = silence_seconds
        self.min_speech_chunks = min_speech_chunks
        self.is_running = False
        self.stream = None

        self.on_audio_chunk: Optional[Callable] = None
        self.on_voice_start: Optional[Callable] = None
        self.on_voice_end: Optional[Callable] = None

        self.in_speech = False
        self.silence_timer = 0
        self._speech_chunk_count = 0

        # Will be set from outside (main) so callbacks know which loop to use
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    async def initialize(self):
        """Initialize audio device (optional logging)"""
        try:
            devices = sd.query_devices()
            default_input = sd.default.device[0]
            if default_input is not None:
                info = devices[default_input]
                print(f"Using microphone: {info['name']}")
            else:
                print("Warning: No default input device configured")
        except Exception as e:
            print(f"Warning: Could not query audio devices: {e}")

    def _run_coro(self, coro):
        """Run coroutine from callback thread."""
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(coro, self.loop)

    def mic_callback(self, indata, frames, time_, status):
        """Callback for audio stream - runs in PortAudio thread"""
        if status:
            pass  # suppress PortAudio status noise

        audio_data = indata.copy()
        volume = float(np.max(np.abs(audio_data)))



        if volume > self.threshold and not self.in_speech:
            self._speech_chunk_count += 1
            if self._speech_chunk_count >= self.min_speech_chunks:
                self.in_speech = True
                self.silence_timer = 0
                print(f"🔴 Voice detected — recording started")
                if self.on_voice_start:
                    self._run_coro(self.on_voice_start())
        elif volume <= self.threshold and not self.in_speech:
            self._speech_chunk_count = 0

        elif volume < self.threshold and self.in_speech:
            self.silence_timer += 1
            chunks_needed = max(1, round(self.silence_seconds * self.sample_rate / self.chunk_size))
            if self.silence_timer >= chunks_needed:
                self.in_speech = False
                self.silence_timer = 0
                print("⏹️  Voice ended — sending to AI")
                if self.on_voice_end:
                    self._run_coro(self.on_voice_end())
        elif volume >= self.threshold and self.in_speech:
            self.silence_timer = 0

        if self.in_speech and self.on_audio_chunk:
            pcm_data = (audio_data * 32767).astype(np.int16)
            encoded = base64.b64encode(pcm_data.tobytes()).decode()
            self._run_coro(self.on_audio_chunk(encoded))

    async def start(self):
        """Start audio capture"""
        if self.is_running:
            return

        self.is_running = True

        if self.loop is None:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                self.loop = None

        await self.initialize()

        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.chunk_size,
            callback=self.mic_callback,
            latency="high",
        )
        self.stream.start()
        print("✓ Audio capture started")

    async def stop(self):
        """Stop audio capture"""
        if not self.is_running:
            return

        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        self.is_running = False
        print("✓ Audio capture stopped")