"""Paired normal-chat latency benchmark; credentials remain in memory.

Use on isolated, prestarted Onyx API containers. Every NDJSON packet receives a
monotonic client timestamp; final-answer TTFT is identified after the turn ends.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

from onyx.auth.users import TenantAwareRedisStrategy, auth_backend
from onyx.db.harness_v2 import prepare_harness
from onyx.db.headless_harness import prepare_headless_user


async def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    panel = json.loads(Path(sys.argv[2]).read_text())
    user, _ = prepare_headless_user("0b86b1df-a5c9-45fc-a907-88d3684b5c21")
    prepared = prepare_harness(user, "OpenAI Default", "gpt-5.6-sol", 0, False)
    strategy = TenantAwareRedisStrategy(lifetime_seconds=7200)
    token = await strategy.write_token(user)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(240, connect=5),
        cookies={auth_backend.transport.cookie_name: token},  # ty: ignore[unresolved-attribute] JWT transport provides the cookie name.
    ) as client:

        async def run(arm, q, warmup=False):
            base = config["arms"][arm]["api"]
            out = {
                "arm": arm,
                "question_id": q["question_id"],
                "category": q["question_type"],
                "warmup": warmup,
            }
            events = []
            texts = []
            started = None
            try:
                r = await client.post(
                    base + "/chat/create-chat-session",
                    json={"description": "TTFT " + arm + " " + q["question_id"]},
                )
                r.raise_for_status()
                sid = r.json()["chat_session_id"]
                out["session_id"] = sid
                r = await client.put(
                    base + "/chat/update-chat-session-reasoning",
                    json={"chat_session_id": sid, "reasoning_effort_override": "off"},
                )
                r.raise_for_status()
                payload = {
                    "chat_session_id": sid,
                    "message": q["question"],
                    "stream": True,
                    "allowed_tool_ids": [prepared.search_tool_id],
                    "llm_override": {
                        "model_provider": "OpenAI Default",
                        "model_version": "gpt-5.6-sol",
                    },
                }
                started = time.monotonic()
                async with asyncio.timeout(300):
                    async with client.stream(
                        "POST", base + "/chat/send-chat-message", json=payload
                    ) as r:
                        out["http_status"] = r.status_code
                        out["headers_s"] = time.monotonic() - started
                        r.raise_for_status()
                        async for line in r.aiter_lines():
                            if not line:
                                continue
                            now = time.monotonic() - started
                            item = json.loads(line)
                            obj = item.get("obj", {})
                            kind = obj.get("type") or (
                                "error"
                                if "error" in item or "error_msg" in item
                                else "message_ids"
                            )
                            event = {
                                "seconds": now,
                                "type": kind,
                                "placement": item.get("placement"),
                            }
                            if kind == "message_delta":
                                content = obj.get("content", "")
                                event["text"] = content
                                if content.strip():
                                    texts.append(event)
                            if kind == "stop":
                                event["stop_reason"] = obj.get("stop_reason")
                            if kind == "error":
                                event["error"] = item
                            events.append(event)
                out["stream_end_s"] = time.monotonic() - started
                r = await client.get(base + "/chat/get-chat-session/" + sid)
                r.raise_for_status()
                messages = r.json()["messages"]
                m = next(
                    m for m in reversed(messages) if m["message_type"] == "assistant"
                )
                out["saved_answer"] = m["message"]
                out["saved_error"] = m.get("error")
                out["request_params"] = m.get("request_params")
                out["model"] = m.get("model_display_name")
                out["citations"] = m.get("citations")
                out["first_visible_text_s"] = texts[0]["seconds"] if texts else None
                out["first_activity_s"] = next(
                    (
                        e["seconds"]
                        for e in events
                        if e["type"]
                        in ("message_delta", "search_tool_start", "reasoning_delta")
                    ),
                    None,
                )
                # V1 emits preambles and final text in distinct turn placements; v2's
                # bridge does likewise. Last answer block must agree with saved final text.
                if texts:
                    final_placement = texts[-1]["placement"]
                    final = [e for e in texts if e["placement"] == final_placement]
                    out["first_final_text_s"] = final[0]["seconds"]
                    out["last_final_text_s"] = final[-1]["seconds"]
                    out["final_chunk_count"] = len(final)
                    emitted = "".join(
                        str(e["text"])
                        for e in events
                        if e["type"] == "message_delta"
                        and e["placement"] == final_placement
                    )
                    # Some v1 versions save preambles with the final; retain an audit flag.
                    out["final_matches_saved"] = (
                        emitted.strip() in m["message"].strip()
                        or m["message"].strip() in emitted.strip()
                    )
                else:
                    out["first_final_text_s"] = None
                    out["final_matches_saved"] = False
                out["search_calls"] = sum(
                    e["type"] == "search_tool_start" for e in events
                )
                out["stop_seen"] = any(e["type"] == "stop" for e in events)
                out["success"] = (
                    bool(m["message"])
                    and not m.get("error")
                    and out["stop_seen"]
                    and not any(e["type"] == "error" for e in events)
                )
            except Exception as exc:
                out["success"] = False
                out["exception"] = type(exc).__name__ + ": " + str(exc)
                if started:
                    out["elapsed_on_error_s"] = time.monotonic() - started
            out["events"] = events
            print("TTFT_RESULT " + json.dumps(out), flush=True)
            return out

        try:
            for arm in config["arms"]:
                for _ in range(45):
                    try:
                        r = await client.get(config["arms"][arm]["api"] + "/health")
                        r.raise_for_status()
                        break
                    except Exception:
                        await asyncio.sleep(2)
                else:
                    raise RuntimeError("API did not become ready")
            warm = {
                "question_id": "warmup",
                "question_type": "warmup",
                "question": "What are the default size limits for file uploads and total request size for the new multipart upload support on the OpenAI-compatible API endpoints?",
            }
            await asyncio.gather(*(run(a, warm, True) for a in config["arms"]))
            sem = asyncio.Semaphore(config["concurrency_per_arm"])

            async def pair(i, q):
                async with sem:
                    arms = ["v1", "v2"] if i % 2 == 0 else ["v2", "v1"]
                    return await asyncio.gather(*(run(a, q) for a in arms))

            await asyncio.gather(*(pair(i, q) for i, q in enumerate(panel)))
            print("TTFT_COMPLETE", flush=True)
        finally:
            await strategy.destroy_token(token, user)


asyncio.run(main())
