# from __future__ import annotations

# import asyncio
# import logging
# import uuid
# from dataclasses import dataclass

# import numpy as np
# from scipy.signal import resample_poly

# from dotenv import load_dotenv
# from livekit.agents import JobContext, WorkerOptions, cli, APIConnectOptions, tts
# from livekit.agents.voice import Agent, AgentSession
# from livekit.plugins import openai, silero

# from supertonic import TTS as SupertonicEngine

# load_dotenv()
# logger = logging.getLogger("voice-agent")
# logger.setLevel(logging.INFO)

# SUPERTONIC_NATIVE_RATE = 44_100
# LIVEKIT_SAMPLE_RATE    = 24_000
# LIVEKIT_CHANNELS       = 1


# # ─── Local TTS: Supertonic ────────────────────────────────────────────────────

# @dataclass
# class SupertonicTTSOptions:
#     voice_name  : str   = "M2"
#     lang        : str   = "en"
#     total_steps : int   = 8
#     speed       : float = 1.05


# class SupertonicChunkedStream(tts.ChunkedStream):

#     def __init__(self, *, tts_instance: "SupertonicTTS", input_text: str, opts: SupertonicTTSOptions, conn_options: APIConnectOptions) -> None:
#         super().__init__(tts=tts_instance, input_text=input_text, conn_options=conn_options)
#         self._opts = opts
#         self._tts  = tts_instance

#     async def _run(self, output_emitter) -> None:
#         loop = asyncio.get_event_loop()
#         wav, duration = await loop.run_in_executor(
#             None, self._synthesize_sync, self._input_text
#         )

#         audio_f32 = wav.squeeze()
#         audio_resampled = resample_poly(audio_f32, up=80, down=147).astype(np.float32)
#         audio_int16 = (audio_resampled * 32767).clip(-32768, 32767).astype(np.int16)

#         output_emitter.initialize(
#             request_id=uuid.uuid4().hex,
#             sample_rate=LIVEKIT_SAMPLE_RATE,
#             num_channels=LIVEKIT_CHANNELS,
#             mime_type="audio/pcm",
#             stream=False,
#         )
#         output_emitter.push(audio_int16.tobytes())
#         output_emitter.flush()
#         logger.debug("Supertonic synthesised %.2fs of audio", duration[0])

#     def _synthesize_sync(self, text: str):
#         engine = self._tts._engine
#         style  = engine.get_voice_style(voice_name=self._opts.voice_name)
#         wav, duration = engine.synthesize(
#             text=text,
#             lang=self._opts.lang,
#             voice_style=style,
#             total_steps=self._opts.total_steps,
#             speed=self._opts.speed,
#         )
#         return wav, duration


# class SupertonicTTS(tts.TTS):

#     def __init__(self, *, voice_name: str = "M2", lang: str = "en", total_steps: int = 8, speed: float = 1.05) -> None:
#         super().__init__(
#             capabilities=tts.TTSCapabilities(streaming=False),
#             sample_rate=LIVEKIT_SAMPLE_RATE,
#             num_channels=LIVEKIT_CHANNELS,
#         )
#         self._opts = SupertonicTTSOptions(voice_name=voice_name, lang=lang, total_steps=total_steps, speed=speed)
#         logger.info("Loading Supertonic3 model…")
#         self._engine = SupertonicEngine(auto_download=True)
#         logger.info("Supertonic3 model loaded")

#     def synthesize(self, text: str, *, conn_options: APIConnectOptions) -> SupertonicChunkedStream:
#         print(text)
#         return SupertonicChunkedStream(
#             tts_instance=self,
#             input_text=text,
#             opts=self._opts,
#             conn_options=conn_options,
#         )


# # ─── Agent ────────────────────────────────────────────────────────────────────

# class VoiceAgent(Agent):
#     def __init__(self) -> None:
#         super().__init__(
#             instructions="""
# You are a helpful voice assistant.
# Be friendly and conversational.
# Keep answers short since the user is listening, not reading.
#             """,
#             stt=openai.STT(model="whisper-1"),
#             llm=openai.LLM(model="gpt-4o-mini"),
#             tts=SupertonicTTS(voice_name="M2", lang="en", total_steps=8, speed=1.05),
#         )

#     async def on_enter(self):
#         self.session.generate_reply()

#     async def on_user_turn_completed(self, turn_ctx, new_message):
#         logger.info(">>> STT heard: %r", new_message.text_content)
#         await super().on_user_turn_completed(turn_ctx, new_message)

#     async def on_agent_turn_completed(self, turn_ctx, new_message):
#         logger.info(">>> LLM replied: %r", new_message.text_content)
#         await super().on_agent_turn_completed(turn_ctx, new_message)


# async def entrypoint(ctx: JobContext):
#     logger.info("User connected to room: %s", ctx.room.name)
#     session = AgentSession(vad=silero.VAD.load())
#     await session.start(agent=VoiceAgent(), room=ctx.room)


# if __name__ == "__main__":
#     cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
