"""Groq client using Whisper + LLaMA"""

import asyncio
import base64
import io
import re
import wave
from typing import Callable, Optional
from groq import AsyncGroq
from token_storage import load_token


class OpenAIRealtimeClient:

    def __init__(self):
        self.is_connected = False
        self.client: Optional[AsyncGroq] = None
        self._audio_chunks: list[bytes] = []
        self._instructions = "You are a helpful interview assistant."
        self._history: list[dict] = []
        self.on_transcription: Optional[Callable] = None
        self.on_answer: Optional[Callable] = None

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

    def _to_wav(self, chunks: list[bytes]) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"".join(chunks))
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
            print("❌ No audio buffered")
            return

        print("📤 Transcribing audio with Whisper...")
        wav_bytes = self._to_wav(self._audio_chunks)
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

            # Filter out garbage transcriptions
            words = text.split()
            if not text or len(words) < 2 or len(text) < 8:
                print("⚠️  Transcription too short or unclear — skipping")
                return

            if self.on_transcription:
                await self.on_transcription(text)

            self._history.append({"role": "user", "content": text})

            response = await self._call_with_retry(
                self.client.chat.completions.create,
                model="llama-3.3-70b-versatile",
                max_tokens=800,
                messages=[{"role": "system", "content": self._instructions}] + self._history,
            )
            answer = response.choices[0].message.content
            self._history.append({"role": "assistant", "content": answer})
            # Keep last 10 exchanges to avoid token limit
            if len(self._history) > 20:
                self._history = self._history[-20:]

            if self.on_answer:
                await self.on_answer([{"type": "message", "content": [{"type": "text", "text": answer}]}])

        except Exception as e:
            print(f"❌ API error: {e}")

    async def disconnect(self):
        self.is_connected = False
        print("✓ Disconnected")
