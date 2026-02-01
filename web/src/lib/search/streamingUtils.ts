import { PacketType } from "@/app/app/services/lib";

export async function* handleSSEStream<T extends PacketType>(
  streamingResponse: Response,
  signal?: AbortSignal
): AsyncGenerator<T, void, unknown> {
  const reader = streamingResponse.body?.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  if (signal) {
    signal.addEventListener("abort", () => {
      console.log("aborting");
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
        console.error("Error parsing SSE data:", error);

        // Detect JSON objects (ie. check if parseable json has been accumulated)
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

  // Process any remaining data in the buffer
  if (buffer.trim() !== "") {
    try {
      const data = JSON.parse(buffer) as T;
      yield data;
    } catch (error) {
      console.error("Error parsing remaining buffer:", error);
    }
  }
}
