/**
 * The dev API proxy forwards request bodies to the backend with Node fetch,
 * which refuses some hop-by-hop request headers that clients such as curl send.
 */
import { createServer, type Server } from "http";
import type { AddressInfo } from "net";
import { NextRequest } from "next/server";

type RouteModule = typeof import("@/app/api/[...path]/route");

let server: Server;
let receivedBody: string | null = null;
let route: RouteModule;
const savedEnv = { ...process.env };

beforeAll(async () => {
  server = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", () => {
      receivedBody = Buffer.concat(chunks).toString();
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true }));
    });
  });
  await new Promise<void>((resolve) =>
    server.listen(0, "127.0.0.1", () => resolve())
  );
  const { port } = server.address() as AddressInfo;
  process.env.INTERNAL_URL = `http://127.0.0.1:${port}`;
  process.env.OVERRIDE_API_PRODUCTION = "true";
  route = await import("@/app/api/[...path]/route");
});

afterAll(async () => {
  process.env = savedEnv;
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

beforeEach(() => {
  receivedBody = null;
});

function upload(headers: Record<string, string>): NextRequest {
  return new NextRequest("http://localhost:3000/api/skills/plugins/inspect", {
    method: "POST",
    headers: { "content-type": "text/plain", ...headers },
    body: "bundle bytes",
    duplex: "half",
  });
}

describe("API proxy route", () => {
  it.each([
    ["expect", "100-continue"],
    ["transfer-encoding", "chunked"],
    ["keep-alive", "timeout=5"],
    ["upgrade", "h2c"],
  ])(
    "forwards a request that has a %s header",
    async (name: string, value: string) => {
      const response = await route.POST(upload({ [name]: value }), {
        params: Promise.resolve({ path: ["skills", "plugins", "inspect"] }),
      });

      expect(response.status).toBe(200);
      expect(await response.json()).toEqual({ ok: true });
      expect(receivedBody).toBe("bundle bytes");
    }
  );
});
