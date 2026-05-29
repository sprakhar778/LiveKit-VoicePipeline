from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from livekit import api as lkapi

from app import agent_server

load_dotenv()

API_KEY     = os.environ["LIVEKIT_API_KEY"]
API_SECRET  = os.environ["LIVEKIT_API_SECRET"]
LIVEKIT_URL = os.environ["LIVEKIT_URL"]
ROOM_NAME   = os.getenv("LIVEKIT_ROOM", "my-room")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[startup] starting agent worker…", flush=True)
    task = asyncio.create_task(agent_server.run(devmode=True))
    print("[startup] agent worker running", flush=True)
    yield
    print("[shutdown] stopping agent worker…", flush=True)
    task.cancel()
    await agent_server.aclose()


app = FastAPI(lifespan=lifespan)


def make_token() -> str:
    return (
        lkapi.AccessToken(api_key=API_KEY, api_secret=API_SECRET)
        .with_identity("user1")
        .with_name("User")
        .with_grants(lkapi.VideoGrants(room_join=True, room=ROOM_NAME))
        .to_jwt()
    )


async def dispatch_agent() -> None:
    async with lkapi.LiveKitAPI(url=LIVEKIT_URL, api_key=API_KEY, api_secret=API_SECRET) as lk:
        try:
            resp = await lk.room.list_participants(lkapi.ListParticipantsRequest(room=ROOM_NAME))
            if any(p.kind == 4 for p in resp.participants):
                print("[dispatch] agent already in room, skipping")
                return
        except Exception as e:
            print(f"[dispatch] list_participants: {e}")

        try:
            existing = await lk.agent_dispatch.list_dispatch(lkapi.ListAgentDispatchRequest(room=ROOM_NAME))
            if existing.agent_dispatches:
                print("[dispatch] pending dispatch found, skipping")
                return
        except Exception as e:
            print(f"[dispatch] list_dispatch: {e}")

        await lk.agent_dispatch.create_dispatch(lkapi.CreateAgentDispatchRequest(agent_name="voice-agent", room=ROOM_NAME))
        print(f"[dispatch] agent dispatched to '{ROOM_NAME}'")


@app.get("/token")
async def get_token():
    print(f"\n[/token] browser connected → room '{ROOM_NAME}'", flush=True)
    try:
        await dispatch_agent()
    except Exception as e:
        import traceback
        print(f"[/token] dispatch failed: {e}", flush=True)
        traceback.print_exc()
    token = make_token()
    print(f"[/token] JWT issued for user1", flush=True)
    return {"url": LIVEKIT_URL, "token": token}


@app.get("/health")
async def health():
    print("[/health] ping", flush=True)
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=".", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
