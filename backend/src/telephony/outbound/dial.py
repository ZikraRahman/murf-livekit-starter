"""Dispatch the outbound agent to place a SIP call."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid

from dotenv import load_dotenv
from livekit import api

load_dotenv(".env.local")
AGENT_NAME = "outbound-agent"
DEMO_USER_ID = "anon_00000000-0000-4000-8000-000000000006"


async def dial(destination: str, room_name: str, user_id: str) -> None:
    livekit = api.LiveKitAPI()
    try:
        await livekit.room.create_room(api.CreateRoomRequest(name=room_name))
        await livekit.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME,
                room=room_name,
                metadata=json.dumps({"phone_number": destination, "user_id": user_id}),
            )
        )
    finally:
        await livekit.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Place an outbound Linphone call.")
    parser.add_argument("--to", required=True, help="SIP URI or E.164 destination")
    parser.add_argument("--room", default=None, help="Optional LiveKit room name")
    parser.add_argument(
        "--user-id",
        default=DEMO_USER_ID,
        help="Existing memory user_id to use for this outbound call",
    )
    args = parser.parse_args()
    room_name = args.room or f"outbound-{uuid.uuid4().hex[:8]}"
    asyncio.run(dial(args.to, room_name, args.user_id))
    print(
        f"Dispatched {AGENT_NAME} to room '{room_name}' to call {args.to} "
        f"using memory user_id '{args.user_id}'."
    )


if __name__ == "__main__":
    main()
