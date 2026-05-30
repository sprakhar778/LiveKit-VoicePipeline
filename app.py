from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass
from prompt import PROMPT

import numpy as np
from scipy.signal import resample_poly
from dotenv import load_dotenv

from livekit.agents import JobContext, WorkerOptions, cli, APIConnectOptions, tts
from livekit.agents.worker import AgentServer
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import openai, silero, langchain

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from langchain_core.messages import ToolMessage

from supertonic import TTS as SupertonicEngine

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

load_dotenv()

logger = logging.getLogger("voice-agent")
logger.setLevel(logging.INFO)

SUPERTONIC_NATIVE_RATE = 44_100
LIVEKIT_SAMPLE_RATE    = 24_000
LIVEKIT_CHANNELS       = 1

# ──────────────────────────────────────────────────────────────────────────────
# Text utilities
# ──────────────────────────────────────────────────────────────────────────────

def split_clauses(text: str) -> list[str]:
    """Split text at sentence and comma boundaries so each clause stays under 300 chars (1 Supertonic chunk)."""
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

# ──────────────────────────────────────────────────────────────────────────────
# TTS — Supertonic
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SupertonicTTSOptions:
    voice_name  : str   = "M2"
    lang        : str   = "en"
    total_steps : int   = 8
    speed       : float = 1.05


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
                t0 = time.perf_counter()
                wav, dur = await loop.run_in_executor(None, self._synthesize_sync, clause)
                elapsed  = time.perf_counter() - t0
                print(f"  [TTS] {i}/{len(clauses)} {elapsed:.2f}s → {dur[0]:.2f}s audio", flush=True)
                audio = (resample_poly(wav.squeeze(), 80, 147) * 32767).clip(-32768, 32767).astype(np.int16)
                output_emitter.push(audio.tobytes())

        output_emitter.flush()

    def _synthesize_sync(self, text: str):
        engine = self._tts._engine
        style  = engine.get_voice_style(voice_name=self._opts.voice_name)
        wav, duration = engine.synthesize(
            text=text,
            lang=self._opts.lang,
            voice_style=style,
            total_steps=self._opts.total_steps,
            speed=self._opts.speed,
        )
        return wav, duration


class SupertonicTTS(tts.TTS):

    def __init__(self, *, voice_name: str = "M2", lang: str = "en", total_steps: int = 8, speed: float = 1.05) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=LIVEKIT_SAMPLE_RATE,
            num_channels=LIVEKIT_CHANNELS,
        )
        self._opts   = SupertonicTTSOptions(voice_name=voice_name, lang=lang, total_steps=total_steps, speed=speed)
        self._sem    = asyncio.Semaphore(1)
        logger.info("Loading Supertonic3 model…")
        self._engine = SupertonicEngine(auto_download=True)
        logger.info("Supertonic3 model loaded")

    def synthesize(self, text: str, *, conn_options: APIConnectOptions) -> SupertonicChunkedStream:
        return SupertonicChunkedStream(
            tts_instance=self,
            input_text=text,
            opts=self._opts,
            conn_options=conn_options,
        )

# ──────────────────────────────────────────────────────────────────────────────
# LLM — LangChain agent + tools
# ──────────────────────────────────────────────────────────────────────────────

@tool
def get_data():
    """Get the current device/project data."""
    return """
Project Name: Misso Robotic System
Client: Meril Life Sciences
Device ID: DHF-RBT-042
Status: Active Development

Current Tasks:
- Integrating LiDAR-based navigation
- Optimizing voice command pipeline
- Testing obstacle avoidance module
- Improving battery monitoring dashboard

Recent Metrics:
- Uptime: 98.7%
- Battery Health: 94%
- Navigation Accuracy: 96.2%
- Voice Command Success Rate: 92.8%

Last Update:
The robotics team completed indoor mapping tests in the manufacturing unit.
The system successfully navigated 1.8 km of test routes and identified
37 simulated obstacles with a 96% detection rate.
"""


agent_graph = create_agent(
    system_prompt=(
        PROMPT
        + "\nUse get_data tool when asked about the current device or project."
        + " Keep all answers under 3 sentences — this is a voice interface."
    ),
    model=ChatOpenAI(model="gpt-4o-mini", temperature=0.7, max_tokens=80),
    tools=[get_data],
)

raw_astream = agent_graph.astream

#Filter out ToolMessage from agent stream
async def filtered_astream(*args, **kwargs):
    async for item in raw_astream(*args, **kwargs):
        if isinstance(item, tuple) and isinstance(item[0], ToolMessage):
            continue
        if isinstance(item, ToolMessage):
            continue
        yield item

agent_graph.astream = filtered_astream

# ──────────────────────────────────────────────────────────────────────────────
# Voice agent
# ──────────────────────────────────────────────────────────────────────────────

class VoiceAgent(Agent):

    def __init__(self) -> None:
        super().__init__(
            instructions=PROMPT,
            stt=openai.STT(model="whisper-1"),
            llm=langchain.LLMAdapter(agent_graph),
            tts=SupertonicTTS(voice_name="M2", lang="en", total_steps=8, speed=1.1),
        )
        self._t_user_turn: float = 0.0

    async def on_enter(self):
        await self.session.say("Hello! I'm your voice assistant. Go ahead and speak.")

    async def on_user_turn_completed(self, turn_ctx, new_message):
        self._t_user_turn = time.perf_counter()
        print(f"\n[STT] {new_message.text_content}", flush=True)
        await super().on_user_turn_completed(turn_ctx, new_message)

    async def on_agent_turn_completed(self, turn_ctx, new_message):
        llm_ms = (time.perf_counter() - self._t_user_turn) * 1000
        print(f"[TIMER] STT→LLM→TTS pipeline: {llm_ms:.0f}ms", flush=True)
        print(f"[LLM]  {new_message.text_content}\n", flush=True)
        await super().on_agent_turn_completed(turn_ctx, new_message)

# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────────

async def entrypoint(ctx: JobContext):
    logger.info("User connected to room: %s", ctx.room.name)

    vad = silero.VAD.load(
        activation_threshold=0.5,     # start speech above this confidence
        deactivation_threshold=0.35,  # end speech below this confidence
        min_speech_duration=0.1,      # ignore blips shorter than 100ms
        min_silence_duration=0.8,     # wait 800ms of silence before ending turn
        prefix_padding_duration=0.3,  # keep 300ms before detected speech onset
    )

    session = AgentSession(
        vad=vad,
        turn_handling={
            "turn_detection": "vad",
            "endpointing": {
                "min_delay": 0.5,  # wait at least 500ms after VAD silence before STT
                "max_delay": 2.0,  # give slow speakers up to 2s
            },
        },
    )

    await session.start(agent=VoiceAgent(), room=ctx.room)


agent_server = AgentServer()
agent_server.rtc_session(entrypoint, agent_name="voice-agent")

if __name__ == "__main__":
    import asyncio
    asyncio.run(agent_server.run(devmode=True))