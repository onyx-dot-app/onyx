"""KVM test api_server stand-in: the node routes of the api_server, plus a
test-only route that writes the placement record (the placement code writes
it in production).

Env: the usual Onyx env, SANDBOX_NODE_REGISTRATION_SECRET, HARNESS_REG_PORT.
"""

import os
import time
from uuid import UUID

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from onyx.cache.factory import get_cache_backend
from onyx.microvm.registry import (
    SandboxPlacement,
    write_sandbox_placement,
)
from onyx.server.features.microvm.api import router as sandbox_node_router


class Placement(BaseModel):
    sandbox_id: UUID
    tenant_id: str
    node_id: str
    generation: int
    attempt: int = 1


app = FastAPI()
app.include_router(sandbox_node_router)


@app.put("/test/placement")
def put_placement(p: Placement) -> None:
    placement = SandboxPlacement(
        node_id=p.node_id,
        attempt=p.attempt,
        generation=p.generation,
        last_active=int(time.time()),
    )
    if not write_sandbox_placement(
        get_cache_backend(tenant_id=p.tenant_id), p.sandbox_id, placement
    ):
        raise HTTPException(status_code=409, detail="a newer placement exists")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("HARNESS_REG_PORT", "8095")),
        log_level="info",
    )
