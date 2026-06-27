"""Groq client using Whisper + LLaMA with LangChain for better prompting"""

import asyncio
import base64
import io
import re
import wave
import time
from typing import Callable, Optional
import numpy as np
from groq import AsyncGroq
from token_storage import load_token
from langchain_prompt_engine import LangChainPromptEngine


class OpenAIRealtimeClient:

    def __init__(self):
        self.is_connected = False
        self.client: Optional[AsyncGroq] = None
        self._audio_chunks: list[bytes] = []
        self._capture_sample_rate: int = 16000
        self._capture_channels: int = 1
        self._instructions = (
            "You are a technical interview coach. Prioritize factual accuracy, clarity, and realistic examples.\n\n"
            "CRITICAL: Output ONLY raw text — NO SECTION HEADERS/LABELS.\n\n"
            "FORMAT (no labels, just structure naturally):\n"
            "1. Direct answer (1-2 sentences)\n\n"
            "2. Key points (use • or - for bullets):\n"
            "• Point 1\n"
            "• Point 2\n"
            "• Point 3\n\n"
            "3. Example:\n"
            "CODE: <command or code>\n\n"
            "4. Why it matters (1 sentence)\n\n"
            "RULES:\n"
            "- NEVER write 'Direct Answer:', 'Key Points:', 'Why It Matters:' or any section labels\n"
            "- Use • or - for bullets\n"
            "- Use 'CODE: <command>' for examples (no markdown backticks)\n"
            "- Total response: strictly under 100 words\n"
            "- Never invent facts — state uncertainty if unsure\n\n"
            "TONE: Professional, direct, confident."
        )
        self._history: list[dict] = []
        self.on_transcription: Optional[Callable] = None
        self.on_answer: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        self._processing = False  # prevent concurrent API calls
        # Resume text loaded from UI (optional)
        self.resume_text: str = ""
        # Simple dedupe for repeated transcriptions
        self._last_transcription_text: str = ""
        self._last_transcription_ts: float = 0.0

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

    def _truncate_answer(self, answer: str, max_words: int = 100) -> str:
        """Truncate answer to max word count if it exceeds limits."""
        words = answer.split()
        if len(words) > max_words:
            truncated = " ".join(words[:max_words])
            truncated = truncated.rstrip(",;:") + " [...]"
            return truncated
        return answer

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

            # Basic filtering
            words = text.split()
            if not text or len(words) < 2 or len(text) < 8:
                return

            # Deduplicate near-identical transcriptions to avoid repeated triggers
            now = time.time()
            norm_new = re.sub(r"\s+", " ", text.lower()).strip()
            norm_last = re.sub(r"\s+", " ", self._last_transcription_text.lower()).strip()
            if norm_last and norm_new == norm_last and (now - self._last_transcription_ts) < 30:
                # Skip duplicate transcription within 30 seconds
                return

            # Remember last transcription
            self._last_transcription_text = text
            self._last_transcription_ts = now

            if self.on_transcription:
                await self.on_transcription(text)

            self._history.append({"role": "user", "content": text})

            # Build messages with system instruction (skip LangChain for concise answers)
            messages = [
                {"role": "system", "content": self._instructions}
            ]
            
            # Add conversation history (last 3 turns for context)
            messages = messages + self._history[-3:]

            response = await self._call_with_retry(
                self.client.chat.completions.create,
                model="llama-3.1-8b-instant",
                max_tokens=130,
                messages=messages,
            )
            answer = response.choices[0].message.content
            
            # Truncate answer to enforce strict 100-word limit
            answer = self._truncate_answer(answer, max_words=100)
            
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
