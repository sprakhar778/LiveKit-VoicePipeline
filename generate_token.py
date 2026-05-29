import os
from dotenv import load_dotenv
from livekit.api import AccessToken, VideoGrants

load_dotenv()

API_KEY    = os.environ["LIVEKIT_API_KEY"]
API_SECRET = os.environ["LIVEKIT_API_SECRET"]

token = (
    AccessToken(api_key=API_KEY, api_secret=API_SECRET)
    .with_identity("user1")
    .with_name("User")
    .with_grants(VideoGrants(room_join=True, room="my-room"))
    .to_jwt()
)

print("\n── Your LiveKit Token ──────────────────────────────")
print(token)
print("────────────────────────────────────────────────────\n")
