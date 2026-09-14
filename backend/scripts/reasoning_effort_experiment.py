"""Opt-in experiment override at the native Responses request boundary.

The existing backend enum lacks xhigh and internal flows force OFF. Apply one
explicit provider effort to every Sol request, after those translations. Keep
Onyx retrieval, prompts, budget accounting, credentials, and transport intact.
Install after the wire observer so it records the modified outgoing request.
"""

import json


def install_reasoning_effort_override(effort):
    import httpx

    if effort not in {"none", "low", "xhigh"}:
        raise ValueError("Unsupported benchmark reasoning effort")
    original = httpx.Client.send

    def send(client, request, *args, **kwargs):
        if request.url.path == "/v1/responses":
            body = json.loads(request.content)
            if body.get("model") != "gpt-5.6-sol":
                raise ValueError(
                    "Reasoning benchmark requires Sol on every model request"
                )
            body["reasoning"] = {**(body.get("reasoning") or {}), "effort": effort}
            # Keep sampling configuration identical across all arms; reasoning
            # requests do not accept these non-reasoning sampling parameters.
            for key in ("temperature", "top_p", "logprobs"):
                body.pop(key, None)
            headers = [
                (k, v)
                for k, v in request.headers.multi_items()
                if k.lower() != "content-length"
            ]
            request = httpx.Request(
                request.method,
                request.url,
                headers=headers,
                content=json.dumps(body).encode(),
                extensions=request.extensions,
            )
        return original(client, request, *args, **kwargs)

    httpx.Client.send = send
