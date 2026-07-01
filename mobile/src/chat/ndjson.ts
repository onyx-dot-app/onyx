// Pure NDJSON line buffer: holds partial-line state, parses complete lines into
// packets. No platform coupling — the transport feeds it decoded text and owns
// the reader/decoder. (web's handleSSEStream internals.)

export interface NdjsonBuffer<T> {
  // Append text; return packets completed by this chunk. The trailing partial
  // line is retained for the next call.
  pushChunk(text: string): T[];
  // Parse the partial line left at end-of-stream. No brace recovery; a
  // malformed tail is dropped (matches web).
  flush(): T[];
}

function parseLine<T>(line: string, out: T[]): void {
  try {
    out.push(JSON.parse(line) as T);
  } catch (error) {
    console.error("Error parsing NDJSON line:", error);
    // Salvage flat (non-nested) JSON from a bad line; nested objects can't be
    // recovered. Real partial-line completion is the buffer carry-over, not this.
    const jsonObjects = line.match(/\{[^{}]*\}/g);
    if (jsonObjects) {
      for (const jsonObj of jsonObjects) {
        try {
          out.push(JSON.parse(jsonObj) as T);
        } catch (innerError) {
          console.error("Error parsing extracted JSON:", innerError);
        }
      }
    }
  }
}

export function createNdjsonBuffer<T = unknown>(): NdjsonBuffer<T> {
  let buffer = "";

  return {
    pushChunk(text: string): T[] {
      buffer += text;
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      const out: T[] = [];
      for (const line of lines) {
        if (line.trim() === "") continue;
        parseLine(line, out);
      }
      return out;
    },

    flush(): T[] {
      const out: T[] = [];
      if (buffer.trim() !== "") {
        try {
          out.push(JSON.parse(buffer) as T);
        } catch (error) {
          console.error("Error parsing remaining NDJSON buffer:", error);
        }
      }
      buffer = "";
      return out;
    },
  };
}
