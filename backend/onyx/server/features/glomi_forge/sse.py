"""SSE helpers for Glomi Forge event streams."""

import json

from onyx.glomi_forge.schemas.events import ForgeEvent

SSE_KEEPALIVE = ": keepalive\n\n"


def event_to_sse(seq: int, event: ForgeEvent) -> str:
    data = json.loads(event.model_dump_json())
    data["seq"] = seq
    return f"event: message\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
