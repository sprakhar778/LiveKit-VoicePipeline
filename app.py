from __future__ import annotations

import time
import logging

from dotenv import load_dotenv

from livekit.agents import JobContext
from livekit.agents.voice import Agent, AgentSession
from livekit.agents.worker import AgentServer, JobExecutorType
from livekit.plugins import openai, silero, langchain

from prompt import PROMPT
from tts_engine import SupertonicTTS
from project_agent import agent_graph

load_dotenv()

logger = logging.getLogger("voice-agent")
logger.setLevel(logging.INFO)


class VoiceAgent(Agent):

    def __init__(self) -> None:
        super().__init__(
            instructions=PROMPT,
            stt=openai.STT(model="whisper-1"),
            llm=langchain.LLMAdapter(agent_graph),
            tts=SupertonicTTS(voice_name="M1", lang="en", total_steps=8, speed=1.1),
        )
        self._t_user_turn: float = 0.0

    async def on_enter(self):
        await self.session.say("Hello! I'm your voice assistant. Go ahead and speak.")

    async def on_user_turn_completed(self, turn_ctx, new_message):
        self._t_user_turn = time.perf_counter()
        print(f"\n[STT] {new_message.text_content}", flush=True)
        await super().on_user_turn_completed(turn_ctx, new_message)

    async def on_agent_turn_completed(self, turn_ctx, new_message):
        elapsed = (time.perf_counter() - self._t_user_turn) * 1000
        print(f"[TIMER] STT→LLM→TTS pipeline: {elapsed:.0f}ms", flush=True)
        print(f"[LLM]  {new_message.text_content}\n", flush=True)
        await super().on_agent_turn_completed(turn_ctx, new_message)


async def entrypoint(ctx: JobContext):
    logger.info("User connected to room: %s", ctx.room.name)

    vad = silero.VAD.load(
        activation_threshold=0.3,
        deactivation_threshold=0.2,
        min_speech_duration=0.1,
        min_silence_duration=1.0,
        prefix_padding_duration=0.3,
    )

    session = AgentSession(
        vad=vad,
        turn_handling={
            "turn_detection": "vad",
            "endpointing": {
                "min_delay": 0.5,
                "max_delay": 2.0,
            },
        },
    )

    await session.start(agent=VoiceAgent(), room=ctx.room)


agent_server = AgentServer(job_executor_type=JobExecutorType.THREAD)
agent_server.rtc_session(entrypoint, agent_name="voice-agent")

if __name__ == "__main__":
    import asyncio
    asyncio.run(agent_server.run(devmode=True))
