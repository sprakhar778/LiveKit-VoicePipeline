from __future__ import annotations

import asyncio
import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler

from dotenv import load_dotenv
from livekit import api as lkapi

load_dotenv()

API_KEY     = os.environ["LIVEKIT_API_KEY"]
API_SECRET  = os.environ["LIVEKIT_API_SECRET"]
LIVEKIT_URL = os.environ["LIVEKIT_URL"]
ROOM_NAME   = os.getenv("LIVEKIT_ROOM", "my-room")
PORT        = int(os.getenv("PORT", "8080"))


def make_token() -> str:
    return (
        lkapi.AccessToken(api_key=API_KEY, api_secret=API_SECRET)
        .with_identity("user1")
        .with_name("User")
        .with_grants(lkapi.VideoGrants(room_join=True, room=ROOM_NAME))
        .to_jwt()
    )


def dispatch_agent() -> None:
    async def _run():
        async with lkapi.LiveKitAPI(url=LIVEKIT_URL, api_key=API_KEY, api_secret=API_SECRET) as lk:
            try:
                resp = await lk.room.list_participants(lkapi.ListParticipantsRequest(room=ROOM_NAME))
                if any(p.kind == lkapi.ParticipantInfo.Kind.AGENT for p in resp.participants):
                    print(f"Agent already in room, skipping")
                    return
            except Exception:
                pass
            await lk.agent_dispatch.create_dispatch(lkapi.CreateAgentDispatchRequest(agent_name="", room=ROOM_NAME))
            print(f"Agent dispatched to room '{ROOM_NAME}'")
    try:
        asyncio.run(_run())
    except Exception as e:
        print(f"Dispatch warning: {e}")


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path.split("?")[0] == "/token":
            dispatch_agent()
            token = make_token()
            body = json.dumps({"url": LIVEKIT_URL, "token": token}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Open http://localhost:{PORT}/index.html")
    server.serve_forever()
