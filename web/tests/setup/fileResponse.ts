import { ReadableStream } from "stream/web";

/**
 * A `/api/chat/file` response: the file's bytes as a stream, as a browser
 * reads them, with its type and stored name. The jsdom fetch polyfill gives
 * a response no body stream, so the stream is set here.
 */
export function fileResponse(
  body: string,
  contentType: string,
  fileName: string
): Response {
  const response = new Response(null, {
    headers: {
      "Content-Type": contentType,
      "Content-Disposition": `attachment; filename="${fileName}"`,
    },
  });
  const bytes = new TextEncoder().encode(body);
  Object.defineProperty(response, "body", {
    value: new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes);
        controller.close();
      },
    }),
  });
  return response;
}
