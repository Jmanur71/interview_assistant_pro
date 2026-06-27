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
        self._pa: Optional[pyaudio.PyAudio] = None  # kept for compat, unused
        self._threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._mode_lock = None  # initialized in start()

        # In "both" mode we hold one chunk from each source and mix when both arrive
        self._mix_lock = threading.Lock()
        self._pending: dict[str, Optional[tuple]] = {"speaker": None, "mic": None}

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

    def _vad_and_emit_pcm(self, pcm_f32: np.ndarray):
        """Run VAD on already-normalised float32 16k mono array and emit."""
        if len(pcm_f32) == 0:
            return
        normalised = np.clip(pcm_f32, -32768, 32767).astype(np.int16)
        volume = float(np.max(np.abs(pcm_f32))) / 32767.0
        actual_chunk = len(pcm_f32)
        chunks_per_silence = max(1, round(self.silence_seconds * 16000 / actual_chunk))

        if volume > self.threshold and not self.in_speech:
            self._speech_chunk_count += 1
            if self._speech_chunk_count >= self.min_speech_chunks:
                self.in_speech = True
                self.silence_timer = 0
                print("\U0001f534 Voice detected \u2014 recording started")
                if self.on_voice_start:
                    self._run_coro(self.on_voice_start())
        elif volume <= self.threshold and not self.in_speech:
            self._speech_chunk_count = 0
        elif volume < self.threshold and self.in_speech:
            self.silence_timer += 1
            if self.silence_timer >= chunks_per_silence:
                self.in_speech = False
                self.silence_timer = 0
                print("\u23f9\ufe0f  Voice ended \u2014 sending to AI")
                if self.on_voice_end:
                    self._run_coro(self.on_voice_end())
        elif volume >= self.threshold and self.in_speech:
            self.silence_timer = 0

        if self.in_speech and self.on_audio_chunk:
            encoded = base64.b64encode(normalised.tobytes()).decode()
            self._run_coro(self.on_audio_chunk(encoded))

    def _vad_and_emit(self, raw: bytes, rate: int, channels: int):
        """Normalise raw bytes to 16k mono then run VAD."""
        pcm_f32 = self._to_mono16k(raw, rate, channels)
        self._vad_and_emit_pcm(pcm_f32)

    def _to_mono16k(self, raw: bytes, rate: int, channels: int) -> np.ndarray:
        """Convert raw int16 bytes to float32 mono at 16000 Hz."""
        pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        if channels == 2:
            pcm = pcm.reshape(-1, 2).mean(axis=1)
        if rate != 16000:
            new_len = int(len(pcm) * 16000 / rate)
            indices = np.clip((np.arange(new_len) * rate / 16000).astype(np.int32), 0, len(pcm) - 1)
            pcm = pcm[indices]
        return pcm

    def _mix_and_emit(self, source: str, raw: bytes, rate: int, channels: int):
        """Hold chunk from one source; when both arrive, resample to 16k mono, mix and emit."""
        with self._mix_lock:
            self._pending[source] = (raw, rate, channels)
            if self._pending["speaker"] is None or self._pending["mic"] is None:
                return
            spk_raw, spk_rate, spk_ch = self._pending["speaker"]
            mic_raw, mic_rate, mic_ch = self._pending["mic"]
            self._pending["speaker"] = None
            self._pending["mic"] = None

        spk = self._to_mono16k(spk_raw, spk_rate, spk_ch)
        mic = self._to_mono16k(mic_raw, mic_rate, mic_ch)
        length = min(len(spk), len(mic))
        mixed = np.clip((spk[:length] + mic[:length]) / 2, -32768, 32767)
        self._vad_and_emit_pcm(mixed)  # already float32 16k mono, skip re-normalise

    # ---------- capture loops ----------

    def _capture_loop(self, device_index: int, channels: int, rate: int, source: str):
        """Each thread owns its own PyAudio instance to avoid segfaults."""
        # Small stagger to avoid simultaneous PyAudio initialization
        import time
        if source == "mic":
            time.sleep(0.05)
        
        pa = None
        stream = None
        try:
            pa = pyaudio.PyAudio()
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=self.chunk_size,
            )
            while self.is_running and not self._stop_event.is_set():
                try:
                    raw = stream.read(self.chunk_size, exception_on_overflow=False)
                    if self.mode == "both":
                        self._mix_and_emit(source, raw, rate, channels)
                    else:
                        self._vad_and_emit(raw, rate, channels)
                except Exception as e:
                    if self.is_running:
                        print(f"⚠️ {source} read error: {e}")
                        break
        except Exception as e:
            if self.is_running:
                print(f"⚠️ {source} stream error: {e}")
        finally:
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except:
                    pass
            if pa:
                try:
                    pa.terminate()
                except:
                    pass

    def _capture_both_loop(self, spk_info: dict, mic_info: dict):
        """Single thread captures both speaker + mic using one PyAudio instance."""
        pa = None
        spk_stream = None
        mic_stream = None
        try:
            pa = pyaudio.PyAudio()
            
            # Open speaker loopback stream
            spk_stream = pa.open(
                format=pyaudio.paInt16,
                channels=spk_info["channels"],
                rate=spk_info["rate"],
                input=True,
                input_device_index=spk_info["index"],
                frames_per_buffer=self.chunk_size,
            )
            
            # Open mic stream
            mic_stream = pa.open(
                format=pyaudio.paInt16,
                channels=mic_info["channels"],
                rate=mic_info["rate"],
                input=True,
                input_device_index=mic_info["index"],
                frames_per_buffer=self.chunk_size,
            )
            
            while self.is_running and not self._stop_event.is_set():
                try:
                    # Read from both streams
                    spk_raw = spk_stream.read(self.chunk_size, exception_on_overflow=False)
                    mic_raw = mic_stream.read(self.chunk_size, exception_on_overflow=False)
                    
                    # Convert to mono 16k
                    spk = self._to_mono16k(spk_raw, spk_info["rate"], spk_info["channels"])
                    mic = self._to_mono16k(mic_raw, mic_info["rate"], mic_info["channels"])
                    
                    # Check volume on both sources separately
                    spk_volume = float(np.max(np.abs(spk))) / 32767.0 if len(spk) > 0 else 0.0
                    mic_volume = float(np.max(np.abs(mic))) / 32767.0 if len(mic) > 0 else 0.0
                    max_volume = max(spk_volume, mic_volume)
                    
                    actual_chunk = len(mic)
                    chunks_per_silence = max(1, round(self.silence_seconds * 16000 / actual_chunk))
                    
                    # VAD triggers if EITHER speaker OR mic has voice
                    if max_volume > self.threshold and not self.in_speech:
                        self._speech_chunk_count += 1
                        if self._speech_chunk_count >= self.min_speech_chunks:
                            self.in_speech = True
                            self.silence_timer = 0
                            print("\U0001f534 Voice detected \u2014 recording started")
                            if self.on_voice_start:
                                self._run_coro(self.on_voice_start())
                    elif max_volume <= self.threshold and not self.in_speech:
                        self._speech_chunk_count = 0
                    elif max_volume < self.threshold and self.in_speech:
                        self.silence_timer += 1
                        if self.silence_timer >= chunks_per_silence:
                            self.in_speech = False
                            self.silence_timer = 0
                            print("\u23f9\ufe0f  Voice ended \u2014 sending to AI")
                            if self.on_voice_end:
                                self._run_coro(self.on_voice_end())
                    elif max_volume >= self.threshold and self.in_speech:
                        self.silence_timer = 0
                    
                    # Send mixed audio when voice detected
                    if self.in_speech and self.on_audio_chunk:
                        length = min(len(spk), len(mic))
                        mixed = np.clip((spk[:length] + mic[:length]) / 2, -32768, 32767).astype(np.int16)
                        encoded = base64.b64encode(mixed.tobytes()).decode()
                        self._run_coro(self.on_audio_chunk(encoded))
                    
                except Exception as e:
                    if self.is_running:
                        print(f"⚠️ Both mode read error: {e}")
                        break
        except Exception as e:
            if self.is_running:
                print(f"⚠️ Both mode initialization error: {e}")
        finally:
            for stream in [spk_stream, mic_stream]:
                if stream:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except:
                        pass
            if pa:
                try:
                    pa.terminate()
                except:
                    pass

    # ---------- start / stop ----------

    async def start(self):
        if self.is_running:
            return
        if self.loop is None:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
        
        if self._mode_lock is None:
            self._mode_lock = asyncio.Lock()

        self._stop_event.clear()
        self._pending = {"speaker": None, "mic": None}
        
        # Use a temporary PyAudio just to query device info, then discard it
        pa_query = pyaudio.PyAudio()
        self._threads = []
        self.capture_sample_rate = 16000
        self.capture_channels = 1

        try:
            if self.mode == "both":
                # Special case: single thread handles both streams with one PyAudio instance
                loopback = pa_query.get_default_wasapi_loopback()
                mic_index = pa_query.get_default_input_device_info()["index"]
                mic_info = pa_query.get_device_info_by_index(mic_index)
                
                print(f"🔊 Speaker loopback: {loopback['name']}")
                print(f"🎤 Microphone: {mic_info['name']}")
                
                spk_info = {
                    "index": loopback["index"],
                    "rate": int(loopback["defaultSampleRate"]),
                    "channels": min(loopback["maxInputChannels"], 2),
                }
                mic_info_dict = {
                    "index": mic_index,
                    "rate": int(mic_info["defaultSampleRate"]),
                    "channels": 1,
                }
                
                self._threads.append(threading.Thread(
                    target=self._capture_both_loop,
                    args=(spk_info, mic_info_dict),
                    daemon=True,
                ))
                
            elif self.mode == "speaker":
                loopback = pa_query.get_default_wasapi_loopback()
                spk_rate = int(loopback["defaultSampleRate"])
                spk_ch   = min(loopback["maxInputChannels"], 2)
                print(f"🔊 Speaker loopback: {loopback['name']}")
                self._threads.append(threading.Thread(
                    target=self._capture_loop,
                    args=(loopback["index"], spk_ch, spk_rate, "speaker"),
                    daemon=True,
                ))
                
            elif self.mode == "mic":
                mic_index = pa_query.get_default_input_device_info()["index"]
                mic_info  = pa_query.get_device_info_by_index(mic_index)
                mic_rate  = int(mic_info["defaultSampleRate"])
                print(f"🎤 Microphone: {mic_info['name']}")
                self._threads.append(threading.Thread(
                    target=self._capture_loop,
                    args=(mic_index, 1, mic_rate, "mic"),
                    daemon=True,
                ))
        finally:
            pa_query.terminate()  # release query instance before streams open

        self.is_running = True
        for t in self._threads:
            t.start()
        
        # Small delay to let streams initialize
        await asyncio.sleep(0.15)
        print(f"✓ Audio capture started ({self.mode} mode)")

    async def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        self._stop_event.set()
        
        # Wait for threads with timeout
        for t in self._threads:
            t.join(timeout=1.0)
        self._threads = []
        
        # Small delay for cleanup
        await asyncio.sleep(0.2)
        print("\u2713 Audio capture stopped")

    async def set_mode(self, mode: AudioMode):
        """Switch capture mode on the fly."""
        if self._mode_lock is None:
            self._mode_lock = asyncio.Lock()
        
        async with self._mode_lock:  # prevent concurrent switches
            if mode == self.mode:
                return
            await self.stop()
            # Critical: wait for PyAudio resources to fully release
            await asyncio.sleep(0.5)
            self.mode = mode
            self.in_speech = False
            self.silence_timer = 0
            self._speech_chunk_count = 0
            self._pending = {"speaker": None, "mic": None}
            await self.start()
