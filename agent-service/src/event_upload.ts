/** Bounded NDJSON upload. Network backpressure limits how far inference can lead the API. */
export class EventUpload {
  readonly body: ReadableStream<Uint8Array>;
  private controller!: ReadableStreamDefaultController<Uint8Array>;
  private events: Record<string, unknown>[] = [];
  private frames: Uint8Array[] = [];
  private bytes = 0;
  private batchBytes = 0;
  private ending = false;
  private closed = false;
  private timer?: ReturnType<typeof setTimeout>;

  constructor(private readonly batchIntervalMs: number) {
    this.body = new ReadableStream<Uint8Array>(
      {
        start: (controller) => {
          this.controller = controller;
        },
        pull: () => this.drain(),
        cancel: () => this.abort(),
      },
      { highWaterMark: 64 * 1024, size: (chunk) => chunk?.byteLength ?? 0 },
    );
  }

  send(event: Record<string, unknown>) {
    if (this.ending || this.closed)
      throw new Error("Agent event upload closed");
    const bytes = Buffer.byteLength(JSON.stringify(event));
    if (this.bytes + bytes > 1024 * 1024)
      throw new Error("Agent event delivery capacity exceeded");
    this.events.push(event);
    this.bytes += bytes;
    this.batchBytes += bytes;
    if (this.batchBytes >= 32 * 1024) this.flush();
    else this.timer ??= setTimeout(() => this.flush(), this.batchIntervalMs);
  }

  end() {
    if (this.closed || this.ending) return;
    this.flush();
    this.ending = true;
    this.drain();
  }

  abort() {
    clearTimeout(this.timer);
    this.events = [];
    this.frames = [];
    if (!this.closed) {
      this.closed = true;
      this.controller.error(new Error("Agent event upload aborted"));
    }
  }

  private flush() {
    clearTimeout(this.timer);
    this.timer = undefined;
    if (!this.events.length) return;
    const frame = new TextEncoder().encode(
      JSON.stringify({ events: this.events }) + "\n",
    );
    // Include the NDJSON envelope in the accounting until handed to the bounded stream.
    this.bytes += frame.byteLength - this.batchBytes;
    for (let offset = 0; offset < frame.byteLength; offset += 32 * 1024)
      this.frames.push(frame.subarray(offset, offset + 32 * 1024));
    this.events = [];
    this.batchBytes = 0;
    this.drain();
  }

  private drain() {
    if (this.closed) return;
    while (this.frames.length && (this.controller.desiredSize ?? 0) > 0) {
      const frame = this.frames.shift()!;
      this.bytes -= frame.byteLength;
      this.controller.enqueue(frame);
    }
    if (this.ending && !this.frames.length) {
      this.closed = true;
      this.controller.close();
    }
  }
}
