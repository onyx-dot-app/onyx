import { PacketType } from "@/app/chat/lib";

type NonEmptyObject = { [k: string]: any };

const processSingleChunk = <T extends NonEmptyObject>(
  chunk: string,
  currPartialChunk: string | null
): [T | null, string | null] => {
  const completeChunk = (currPartialChunk || "") + chunk;
  try {
    // every complete chunk should be valid JSON
    const chunkJson = JSON.parse(completeChunk);
    return [chunkJson, null];
  } catch (err) {
    // if it's not valid JSON, then it's probably an incomplete chunk
    return [null, completeChunk];
  }
};

export const processRawChunkString = <T extends NonEmptyObject>(
  rawChunkString: string,
  previousPartialChunk: string | null
): [T[], string | null] => {
  /* This is required because, in practice, we see that nginx does not send over
  each chunk one at a time even with buffering turned off. Instead,
  chunks are sometimes in batches or are sometimes incomplete */
  if (!rawChunkString) {
    return [[], null];
  }
  const chunkSections = rawChunkString
    .split("\n")
    .filter((chunk) => chunk.length > 0);
  let parsedChunkSections: T[] = [];
  let currPartialChunk = previousPartialChunk;
  chunkSections.forEach((chunk) => {
    const [processedChunk, partialChunk] = processSingleChunk<T>(
      chunk,
      currPartialChunk
    );
    if (processedChunk) {
      parsedChunkSections.push(processedChunk);
      currPartialChunk = null;
    } else {
      currPartialChunk = partialChunk;
    }
  });

  return [parsedChunkSections, currPartialChunk];
};

export async function* handleStream<T extends NonEmptyObject>(
  streamingResponse: Response
): AsyncGenerator<T[], void, unknown> {
  const reader = streamingResponse.body?.getReader();
  const decoder = new TextDecoder("utf-8");

  let previousPartialChunk: string | null = null;
  while (true) {
    const rawChunk = await reader?.read();
    if (!rawChunk) {
      throw new Error("Unable to process chunk");
    }
    const { done, value } = rawChunk;
    if (done) {
      break;
    }

    const [completedChunks, partialChunk] = processRawChunkString<T>(
      decoder.decode(value, { stream: true }),
      previousPartialChunk
    );
    if (!completedChunks.length && !partialChunk) {
      break;
    }
    previousPartialChunk = partialChunk as string | null;

    yield await Promise.resolve(completedChunks);
  }
}

export async function* handleSSEStream<T extends PacketType>(
  streamingResponse: Response
): AsyncGenerator<T, void, unknown> {
  const reader = streamingResponse.body?.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const rawChunk = await reader?.read();
    if (!rawChunk) {
      throw new Error("Unable to process chunk");
    }
    const { done, value } = rawChunk;
    if (done) {
      break;
    }

    const chunk = decoder.decode(value);
    const lines = chunk.split("\n").filter((line) => line.trim() !== "");

    for (const line of lines) {
      try {
        const data = JSON.parse(line) as T;
        yield data;
      } catch (error) {
        console.error("Error parsing SSE data:", error);
      }
    }
  }
}
