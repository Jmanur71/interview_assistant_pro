"""Low-latency audio capture — speaker loopback, microphone, or both mixed"""

import numpy as np
import asyncio
import base64
import threading
from typing import Callable, Optional, Literal
import pyaudiowpatch as pyaudio

AudioMode = Literal["speaker", "mic", "both"]


class AudioProcessor:

    def __init__(
        self,
        mode: AudioMode = "speaker",
        chunk_size: int = 4096,
        threshold: float = 0.04,
        silence_seconds: float = 2.0,
        min_speech_chunks: int = 2,
    ):
        self.mode = mode
        self.chunk_size = chunk_size
        self.threshold = threshold
        self.silence_seconds = silence_seconds
        self.min_speech_chunks = min_speech_chunks

        self.is_running = False
        self._pa: Optional[pyaudio.PyAudio] = None
        self._threads: list[threading.Thread] = []

        # In "both" mode we hold one chunk from each source and mix when both arrive
        self._mix_lock = threading.Lock()
        self._pending: dict[str, Optional[bytes]] = {"speaker": None, "mic": None}

        self.on_audio_chunk: Optional[Callable] = None
        self.on_voice_start: Optional[Callable] = None
        self.on_voice_end: Optional[Callable] = None

        self.in_speech = False
        self.silence_timer = 0
        self._speech_chunk_count = 0

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.capture_sample_rate: int = 16000
        self.capture_channels: int = 1

    # ---------- helpers ----------

    def _run_coro(self, coro):
        if self.loop:
            asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _vad_and_emit(self, raw: bytes, rate: int, channels: int):
        """Run VAD on raw int16 bytes and fire callbacks."""
        pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32767.0
        volume = float(np.max(np.abs(pcm)))

        chunks_per_silence = max(1, round(self.silence_seconds * rate / self.chunk_size))

        if volume > self.threshold and not self.in_speech:
            self._speech_chunk_count += 1
            if self._speech_chunk_count >= self.min_speech_chunks:
                self.in_speech = True
                self.silence_timer = 0
                print("🔴 Voice detected — recording started")
                if self.on_voice_start:
                    self._run_coro(self.on_voice_start())
        elif volume <= self.threshold and not self.in_speech:
            self._speech_chunk_count = 0
        elif volume < self.threshold and self.in_speech:
            self.silence_timer += 1
            if self.silence_timer >= chunks_per_silence:
                self.in_speech = False
                self.silence_timer = 0
                print("⏹️  Voice ended — sending to AI")
                if self.on_voice_end:
                    self._run_coro(self.on_voice_end())
        elif volume >= self.threshold and self.in_speech:
            self.silence_timer = 0

        if self.in_speech and self.on_audio_chunk:
            encoded = base64.b64encode(raw).decode()
            self._run_coro(self.on_audio_chunk(encoded))

    def _mix_and_emit(self, source: str, raw: bytes, rate: int, channels: int):
        """Hold chunk from one source; when both sources have a chunk, mix and emit."""
        with self._mix_lock:
            self._pending[source] = raw
            if self._pending["speaker"] is None or self._pending["mic"] is None:
                return
            spk = np.frombuffer(self._pending["speaker"], dtype=np.int16).astype(np.float32)
            mic = np.frombuffer(self._pending["mic"], dtype=np.int16).astype(np.float32)
            # Pad / trim to same length
            length = min(len(spk), len(mic))
            mixed = np.clip((spk[:length] + mic[:length]) / 2, -32768, 32767).astype(np.int16)
            self._pending["speaker"] = None
            self._pending["mic"] = None

        self._vad_and_emit(mixed.tobytes(), rate, channels)

    # ---------- capture loops ----------

    def _capture_loop(self, device_index: int, channels: int, rate: int, source: str):
        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=self.chunk_size,
        )
        while self.is_running:
            try:
                raw = stream.read(self.chunk_size, exception_on_overflow=False)
                if self.mode == "both":
                    self._mix_and_emit(source, raw, rate, channels)
                else:
                    self._vad_and_emit(raw, rate, channels)
            except Exception:
                break
        stream.stop_stream()
        stream.close()

    # ---------- start / stop ----------

    async def start(self):
        if self.is_running:
            return
        if self.loop is None:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

        self._pa = pyaudio.PyAudio()
        self._threads = []

        if self.mode in ("speaker", "both"):
            loopback = self._pa.get_default_wasapi_loopback()
            spk_rate = int(loopback["defaultSampleRate"])
            spk_ch = min(loopback["maxInputChannels"], 2)
            self.capture_sample_rate = spk_rate
            self.capture_channels = spk_ch
            print(f"🔊 Speaker loopback: {loopback['name']}")
            self._threads.append(threading.Thread(
                target=self._capture_loop,
                args=(loopback["index"], spk_ch, spk_rate, "speaker"),
                daemon=True,
            ))

        if self.mode in ("mic", "both"):
            mic_index = self._pa.get_default_input_device_info()["index"]
            mic_info = self._pa.get_device_info_by_index(mic_index)
            mic_rate = int(mic_info["defaultSampleRate"])
            mic_ch = 1
            if self.mode == "mic":
                self.capture_sample_rate = mic_rate
                self.capture_channels = mic_ch
            print(f"🎤 Microphone: {mic_info['name']}")
            self._threads.append(threading.Thread(
                target=self._capture_loop,
                args=(mic_index, mic_ch, mic_rate, "mic"),
                daemon=True,
            ))

        self.is_running = True
        for t in self._threads:
            t.start()
        print(f"✓ Audio capture started ({self.mode} mode)")

    async def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        for t in self._threads:
            t.join(timeout=2)
        self._threads = []
        if self._pa:
            self._pa.terminate()
            self._pa = None
        print("✓ Audio capture stopped")

    async def set_mode(self, mode: AudioMode):
        """Switch capture mode on the fly."""
        if mode == self.mode:
            return
        await self.stop()
        self.mode = mode
        self.in_speech = False
        self.silence_timer = 0
        self._speech_chunk_count = 0
        self._pending = {"speaker": None, "mic": None}
        await self.start()
