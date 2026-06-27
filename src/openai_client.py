"""Groq client using Whisper + LLaMA"""

import asyncio
import base64
import io
import re
import wave
from typing import Callable, Optional
import numpy as np
from groq import AsyncGroq
from token_storage import load_token


class OpenAIRealtimeClient:

    def __init__(self):
        self.is_connected = False
        self.client: Optional[AsyncGroq] = None
        self._audio_chunks: list[bytes] = []
        self._capture_sample_rate: int = 16000
        self._capture_channels: int = 1
        self._instructions = (
            "You are an expert technical interview coach specialising in DevOps, Cloud, Linux, and Software Engineering. "
            "When answering interview questions:\n"
            "1. Start with a clear, confident 1-2 sentence direct answer.\n"
            "2. Explain the core concept with a real-world analogy or definition.\n"
            "3. List 3-5 key bullet points using '- ' prefix.\n"
            "4. SINGLE-LINE commands (e.g. shell commands): prefix each with 'CODE: ' on its own line. Example: CODE: free -h\n"
            "5. MULTI-LINE code samples (Python, JS, YAML, etc.): wrap the entire block between "
            "'CODEBLOCK:' on one line and 'ENDCODEBLOCK' on its own line. "
            "Write clean, idiomatic, production-quality code with proper naming. "
            "Never use markdown code fences (no triple backticks).\n"
            "6. After any code, briefly explain what it does in 1-2 lines.\n"
            "7. End with exactly one line starting 'TIP: ' to impress the interviewer.\n"
            "Use **bold** for section headers only. Keep total answer under 400 words. Be precise and interview-ready."
        )
        self._history: list[dict] = []
        self.on_transcription: Optional[Callable] = None
        self.on_answer: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        self._processing = False  # prevent concurrent API calls
        # Resume text loaded from UI (optional)
        self.resume_text: str = ""

    async def connect(self):
        token = load_token()
        if not token:
            raise ValueError("No API token found.")
        print("⏳ Initialising Groq client...")
        self.client = AsyncGroq(api_key=token)
        self.is_connected = True
        print("✓ Groq client ready (Whisper + LLaMA)")

    async def update_session(self, config: dict):
        self._instructions = config.get("instructions", self._instructions)
        print("✓ Session config loaded")

    def _to_wav(self, chunks: list[bytes], sample_rate: int = 16000, channels: int = 1) -> bytes:
        pcm = np.frombuffer(b"".join(chunks), dtype=np.int16)
        # Mix down to mono if stereo
        if channels == 2:
            pcm = pcm.reshape(-1, 2).mean(axis=1).astype(np.int16)
        # Resample to 16000 Hz if needed
        if sample_rate != 16000:
            ratio = 16000 / sample_rate
            new_len = int(len(pcm) * ratio)
            indices = (np.arange(new_len) / ratio).astype(np.int32)
            indices = np.clip(indices, 0, len(pcm) - 1)
            pcm = pcm[indices]
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()

    async def send_audio(self, audio_base64: str):
        if self.is_connected:
            self._audio_chunks.append(base64.b64decode(audio_base64))

    async def _call_with_retry(self, fn, *args, **kwargs):
        for attempt in range(3):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                msg = str(e)
                wait = re.search(r"retry in (\d+)", msg)
                delay = int(wait.group(1)) if wait else 10
                if "429" in msg and attempt < 2:
                    print(f"⚠️  Rate limited — retrying in {delay}s (attempt {attempt + 1}/3)")
                    await asyncio.sleep(delay)
                else:
                    raise

    async def send_turn_end(self):
        if not self.is_connected or not self._audio_chunks:
            return

        if self._processing:
            self._audio_chunks = []  # discard — already busy
            return

        self._processing = True
        wav_bytes = self._to_wav(self._audio_chunks, self._capture_sample_rate, self._capture_channels)
        self._audio_chunks = []

        try:
            transcript = await self._call_with_retry(
                self.client.audio.transcriptions.create,
                model="whisper-large-v3",
                file=("audio.wav", wav_bytes, "audio/wav"),
                language="en",
                prompt="DevOps, CI/CD, Kubernetes, Docker, AWS, deployment, integration, delivery, microservices, cloud, pipeline, interview question:",
            )
            text = transcript.text.strip()

            words = text.split()
            if not text or len(words) < 2 or len(text) < 8:
                return

            if self.on_transcription:
                await self.on_transcription(text)

            self._history.append({"role": "user", "content": text})

            # Build messages; include instructions and optionally the resume
            messages = [{"role": "system", "content": self._instructions}]
            if self.resume_text:
                # include a truncated resume snippet to keep payloads reasonable
                resume_snip = self.resume_text[:3000]
                messages.append({"role": "system", "content": f"Candidate resume:\n{resume_snip}"})

            messages = messages + self._history[-6:]

            response = await self._call_with_retry(
                self.client.chat.completions.create,
                model="llama-3.1-8b-instant",
                max_tokens=700,
                messages=messages,
            )
            answer = response.choices[0].message.content
            self._history.append({"role": "assistant", "content": answer})
            if len(self._history) > 20:
                self._history = self._history[-20:]

            if self.on_answer:
                await self.on_answer([{"type": "message", "content": [{"type": "text", "text": answer}]}])

        except Exception as e:
            if self.on_error:
                await self.on_error(str(e))
        finally:
            self._processing = False

    async def disconnect(self):
        self.is_connected = False
        print("✓ Disconnected")
