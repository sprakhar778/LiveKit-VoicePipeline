from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass

import numpy as np
from scipy.signal import resample_poly

from livekit.agents import APIConnectOptions, tts
from supertonic import TTS as SupertonicEngine
from dotenv import load_dotenv
load_dotenv()

SUPERTONIC_NATIVE_RATE = 44_100
LIVEKIT_SAMPLE_RATE    = 24_000
LIVEKIT_CHANNELS       = 1


def split_clauses(text: str) -> list[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    result = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(s) > 200:
            parts = re.split(r'(?<=[,;])\s+', s)
            result.extend(p.strip() for p in parts if p.strip())
        else:
            result.append(s)
    return result or [text.strip()]


@dataclass
class SupertonicTTSOptions:
    voice_name  : str   = "M1"
    lang        : str   = "en"
    total_steps : int   = 8
    speed       : float = 1.05


# Load once at startup — shared across all TTS instances
print("Loading Supertonic3 model…", flush=True)
_supertonic_engine = SupertonicEngine(auto_download=True)
print("Supertonic3 model loaded", flush=True)


class SupertonicChunkedStream(tts.ChunkedStream):

    def __init__(self, *, tts_instance: "SupertonicTTS", input_text: str, opts: SupertonicTTSOptions, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=tts_instance, input_text=input_text, conn_options=conn_options)
        self._opts = opts
        self._tts  = tts_instance

    async def _run(self, output_emitter) -> None:
        loop    = asyncio.get_event_loop()
        clauses = split_clauses(self._input_text)
        print(f"  [TTS] {len(clauses)} clause(s): {self._input_text!r}", flush=True)

        seg_id = uuid.uuid4().hex
        output_emitter.initialize(
            request_id=seg_id,
            sample_rate=LIVEKIT_SAMPLE_RATE,
            num_channels=LIVEKIT_CHANNELS,
            mime_type="audio/pcm",
            stream=True,
        )
        output_emitter.start_segment(segment_id=seg_id)

        async with self._tts._sem:
            for i, clause in enumerate(clauses, 1):
                t0  = time.perf_counter()
                wav, dur = await loop.run_in_executor(None, self._synthesize_sync, clause)
                elapsed  = time.perf_counter() - t0
                print(f"  [TTS] {i}/{len(clauses)} {elapsed:.2f}s → {dur[0]:.2f}s audio", flush=True)
                audio = (resample_poly(wav.squeeze(), 80, 147) * 32767).clip(-32768, 32767).astype(np.int16)
                output_emitter.push(audio.tobytes())

        output_emitter.flush()

    def _synthesize_sync(self, text: str):
        style = _supertonic_engine.get_voice_style(voice_name=self._opts.voice_name)
        wav, duration = _supertonic_engine.synthesize(
            text=text,
            lang=self._opts.lang,
            voice_style=style,
            total_steps=self._opts.total_steps,
            speed=self._opts.speed,
        )
        return wav, duration


class SupertonicTTS(tts.TTS):

    def __init__(self, *, voice_name: str = "M1", lang: str = "en", total_steps: int = 8, speed: float = 1.05) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=LIVEKIT_SAMPLE_RATE,
            num_channels=LIVEKIT_CHANNELS,
        )
        self._opts   = SupertonicTTSOptions(voice_name=voice_name, lang=lang, total_steps=total_steps, speed=speed)
        self._sem    = asyncio.Semaphore(1)
        self._engine = _supertonic_engine

    def synthesize(self, text: str, *, conn_options: APIConnectOptions) -> SupertonicChunkedStream:
        return SupertonicChunkedStream(
            tts_instance=self,
            input_text=text,
            opts=self._opts,
            conn_options=conn_options,
        )
