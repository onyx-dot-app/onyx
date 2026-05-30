// NDJSON streaming reader — ported from web/src/lib/search/streamingUtils.ts (handleSSEStream).
//
// One intentional delta vs the web original:
//   1. Dropped a stray `console.log("aborting")` and renamed the log to "stream" (it's NDJSON).
//
// IMPORTANT: despite the legacy "SSE" name, the Onyx chat stream is NDJSON — the backend sends
// `json.dumps(...) + "\n"` via get_json_line() in backend/onyx/server/utils.py. The line buffer
// with `lines.pop()` carrying the trailing partial line is LOAD-BEARING: a network chunk boundary
// does NOT align with a JSON-object boundary, and one read may carry several objects. Do NOT swap
// this for an EventSource/SSE client — it would silently drop every packet. See 07-networking-streaming-auth.md.

import type { Packet } from "../types";

export async function* handleSSEStream<T = Packet>(
  streamingResponse: Response,
  signal?: AbortSignal
): AsyncGenerator<T, void, unknown> {
  const reader = streamingResponse.body?.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  if (signal) {
    signal.addEventListener("abort", () => {
      reader?.cancel();
    });
  }
  while (true) {
    const rawChunk = await reader?.read();
    if (!rawChunk) {
      throw new Error("Unable to process chunk");
    }
    const { done, value } = rawChunk;
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.trim() === "") continue;

      try {
        const data = JSON.parse(line) as T;
        yield data;
      } catch (error) {
        console.error("Error parsing stream data:", error);

        // Recover any complete JSON objects embedded in an unparseable line.
        const jsonObjects = line.match(/\{[^{}]*\}/g);
        if (jsonObjects) {
          for (const jsonObj of jsonObjects) {
            try {
              const data = JSON.parse(jsonObj) as T;
              yield data;
            } catch (innerError) {
              console.error("Error parsing extracted JSON:", innerError);
            }
          }
        }
      }
    }
  }

  // Flush any remaining buffered data.
  if (buffer.trim() !== "") {
    try {
      const data = JSON.parse(buffer) as T;
      yield data;
    } catch (error) {
      console.error("Error parsing remaining buffer:", error);
    }
  }
}
