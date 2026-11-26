import * as NodeChild from "node:child_process";
import * as NodeFS from "node:fs";
import * as NodeFSP from "node:fs/promises";
import * as NodeHttp from "node:http";
import * as NodeNet from "node:net";
import * as NodeOS from "node:os";
import * as NodePath from "node:path";
import { chromium } from "playwright-core";
import { encodeJson, FrameDecoder, KIND_JPEG } from "../src/framing.ts";
import { BrowserService } from "../src/service.ts";

const findChrome = (): string => {
  const fromEnv = process.env.ONYX_TEST_CHROME;
  if (fromEnv) return fromEnv;
  const root = NodePath.join(NodeOS.homedir(), ".cache", "ms-playwright");
  const builds = NodeFS.existsSync(root)
    ? NodeFS.readdirSync(root)
        .filter((name) => /^chromium-\d+$/.test(name))
        .sort((a, b) => Number(b.split("-")[1]) - Number(a.split("-")[1]))
    : [];
  for (const build of builds) {
    const chrome = NodePath.join(root, build, "chrome-linux64", "chrome");
    if (NodeFS.existsSync(chrome)) return chrome;
  }
  throw new Error("No Chromium found. Set ONYX_TEST_CHROME.");
};

export type Chrome = { readonly cdpUrl: string; readonly stop: () => Promise<void> };

export const launchChrome = async (): Promise<Chrome> => {
  const profile = await NodeFSP.mkdtemp(NodePath.join(NodeOS.tmpdir(), "onyx-browser-profile-"));
  // No core dumps: a test crashes a renderer on purpose.
  const child = NodeChild.spawn(
    "/bin/sh",
    [
      "-c",
      'ulimit -c 0; exec "$0" "$@"',
      findChrome(),
      "--headless",
      "--remote-debugging-port=0",
      `--user-data-dir=${profile}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--no-sandbox",
      "about:blank",
    ],
    { stdio: "ignore", detached: true },
  );
  // Chrome's helper processes share its process group; kill them all on stop.
  const killAll = () => {
    try {
      if (child.pid !== undefined) process.kill(-child.pid, "SIGKILL");
    } catch {
      child.kill("SIGKILL");
    }
  };
  const portFile = NodePath.join(profile, "DevToolsActivePort");
  const deadline = Date.now() + 20_000;
  let port = "";
  while (Date.now() < deadline) {
    const text = await NodeFSP.readFile(portFile, "utf8").catch(() => "");
    port = text.split("\n")[0] ?? "";
    if (port) break;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  if (!port) {
    killAll();
    throw new Error("Chrome did not write DevToolsActivePort.");
  }
  return {
    cdpUrl: `http://127.0.0.1:${port}`,
    stop: async () => {
      const exited =
        child.exitCode === null && child.signalCode === null
          ? new Promise((resolve) => child.once("exit", resolve))
          : Promise.resolve();
      killAll();
      await exited;
      await NodeFSP.rm(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
    },
  };
};

export type Service = {
  readonly socketPath: string;
  readonly sessionsRoot: string;
  readonly stop: () => Promise<void>;
};

export const startService = async (cdpUrl: string): Promise<Service> => {
  const dir = await NodeFSP.mkdtemp(NodePath.join(NodeOS.tmpdir(), "onyx-browser-service-"));
  const socketPath = NodePath.join(dir, "service.sock");
  const sessionsRoot = NodePath.join(dir, "sessions");
  await NodeFSP.mkdir(sessionsRoot);
  const browser = await chromium.connectOverCDP(cdpUrl);
  const context = browser.contexts()[0];
  if (!context) throw new Error("No default context.");
  const service = new BrowserService({ context, sessionsRoot, log: () => {} });
  service.start();
  const server = NodeNet.createServer({ allowHalfOpen: true }, (socket) => service.handleConnection(socket));
  await new Promise<void>((resolve) => server.listen(socketPath, resolve));
  return {
    socketPath,
    sessionsRoot,
    stop: async () => {
      await new Promise<void>((resolve) => server.close(() => resolve()));
      for (const page of context.pages()) await page.close().catch(() => {});
      await browser.close().catch(() => {});
      await NodeFSP.rm(dir, { recursive: true, force: true });
    },
  };
};

type CallReply =
  | { readonly ok: true; readonly result: Record<string, unknown> }
  | { readonly ok: false; readonly error: { readonly code: string; readonly message: string } };

export const call = (
  socketPath: string,
  chat: string,
  method: string,
  params: Record<string, unknown> = {},
): Promise<CallReply> =>
  new Promise((resolve, reject) => {
    const socket = NodeNet.connect(socketPath);
    const decoder = new FrameDecoder();
    let reply: CallReply | null = null;
    socket.on("connect", () => socket.write(encodeJson({ op: "call", chat, method, params })));
    socket.on("data", (chunk: Buffer) => {
      for (const message of decoder.push(chunk))
        if (message.kind === 1) reply = message.value as CallReply;
    });
    socket.on("error", reject);
    socket.on("close", () => (reply ? resolve(reply) : reject(new Error("closed without reply"))));
  });

export const ok = async (
  socketPath: string,
  chat: string,
  method: string,
  params: Record<string, unknown> = {},
) => {
  const reply = await call(socketPath, chat, method, params);
  if (!reply.ok) throw new Error(`${method} failed: ${reply.error.code}: ${reply.error.message}`);
  return reply.result;
};

type ViewerMessage = Record<string, unknown> & { readonly type: string };

export class ViewerClient {
  readonly messages: Array<ViewerMessage> = [];
  readonly frames: Array<Buffer> = [];
  autoAck = false;
  private readonly socket: NodeNet.Socket;
  private readonly waiters = new Set<() => void>();

  private constructor(socket: NodeNet.Socket) {
    this.socket = socket;
    const decoder = new FrameDecoder();
    socket.on("data", (chunk: Buffer) => {
      for (const message of decoder.push(chunk)) {
        if (message.kind === KIND_JPEG) {
          this.frames.push(message.data);
          if (this.autoAck) this.send({ type: "ack" });
        } else this.messages.push(message.value as ViewerMessage);
      }
      for (const wake of this.waiters) wake();
    });
    socket.on("close", () => {
      for (const wake of this.waiters) wake();
    });
  }

  static connect(socketPath: string, chat: string): Promise<ViewerClient> {
    return new Promise((resolve, reject) => {
      const socket = NodeNet.connect(socketPath);
      socket.on("connect", () => {
        socket.write(encodeJson({ op: "view", chat }));
        resolve(new ViewerClient(socket));
      });
      socket.on("error", reject);
    });
  }

  send(value: Record<string, unknown>) {
    this.socket.write(encodeJson(value));
  }

  async waitFor<A>(check: () => A | undefined | null | false, timeoutMs = 10_000): Promise<A> {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const value = check();
      if (value) return value;
      if (Date.now() > deadline) throw new Error("ViewerClient.waitFor timed out");
      await new Promise<void>((resolve) => {
        const wake = () => {
          this.waiters.delete(wake);
          clearTimeout(timer);
          resolve();
        };
        const timer = setTimeout(wake, 100);
        this.waiters.add(wake);
      });
    }
  }

  message(type: string, match: (message: ViewerMessage) => boolean = () => true) {
    return this.waitFor(() => this.messages.find((m) => m.type === type && match(m)));
  }

  close() {
    this.socket.destroy();
  }
}

export const rawSocket = (socketPath: string): Promise<NodeNet.Socket> =>
  new Promise((resolve, reject) => {
    const socket = NodeNet.connect(socketPath);
    socket.on("connect", () => resolve(socket));
    socket.on("error", reject);
  });

export type Site = { readonly url: string; readonly stop: () => Promise<void> };

const PAGES: Record<string, string> = {
  "/form": `<!doctype html><title>Form page</title>
    <button id="btn" style="position:absolute;left:100px;top:100px;width:200px;height:60px" onclick="document.getElementById('out').textContent='clicked '+(++window.n)">Press me</button>
    <p id="out">not clicked</p>
    <label>Name <input id="name"></label>
    <a href="/second">Second page</a>
    <script>window.n=0</script>`,
  "/second": `<!doctype html><title>Second page</title><h1>Second</h1>`,
  "/animated": `<!doctype html><title>Animated</title>
    <div id="box" style="width:100px;height:100px;background:red;position:absolute"></div>
    <script>let x=0;setInterval(()=>{x=(x+7)%600;document.getElementById('box').style.left=x+'px'},16)</script>`,
  "/upload": `<!doctype html><title>Upload</title>
    <input id="file" type="file" style="position:absolute;left:50px;top:50px;width:300px;height:40px"
      onchange="document.getElementById('picked').textContent='picked '+this.files[0].name">
    <p id="picked">none</p>`,
  "/upload-rewrite": `<!doctype html><title>Upload rewrite</title>
    <input id="file" type="file" style="position:absolute;left:50px;top:50px;width:300px;height:40px"
      onclick="setTimeout(()=>history.replaceState(null,'','/upload-rewrite?rewritten'),300)"
      onchange="document.getElementById('picked').textContent='picked '+this.files[0].name">
    <p id="picked">none</p>`,
  "/download-page": `<!doctype html><title>Downloads</title><a id="dl" href="/file.txt">Get file</a>`,
  "/busy-frame": `<!doctype html><title>Busy frame</title>
    <button id="go" onclick="this.textContent='clicked'">Go</button>
    <iframe id="ad" src="/second"></iframe>
    <script>setTimeout(()=>{document.getElementById('ad').src='/second?reloaded'},300)</script>`,
  "/rewrite": `<!doctype html><title>Rewrite</title>
    <button id="go" onclick="this.textContent='clicked'">Go</button>
    <script>setTimeout(()=>history.replaceState(null,'','/rewrite?ready'),300)</script>`,
  "/retitle": `<!doctype html><title>Before</title><script>setTimeout(()=>{document.title='After'},300)</script>`,
  "/alert": `<!doctype html><title>Alert</title><script>setTimeout(()=>alert('hi'),100)</script>`,
  "/download-storm": `<!doctype html><title>Storm</title><script>
    let left = 40;
    const timer = setInterval(() => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob(["x".repeat(1000)]));
      a.download = "storm.bin";
      a.click();
      if (--left === 0) clearInterval(timer);
    }, 100);</script>`,
  "/popup": `<!doctype html><title>Opener</title><a id="pop" href="/second" target="_blank">Open popup</a>`,
};

export const startSite = async (): Promise<Site> => {
  const server = NodeHttp.createServer((request, response) => {
    const path = (request.url ?? "/").split("?")[0] ?? "/";
    if (path === "/file.txt") {
      response.writeHead(200, {
        "content-type": "application/octet-stream",
        "content-disposition": 'attachment; filename="report.txt"',
      });
      response.end("downloaded content");
      return;
    }
    if (path === "/long-name") {
      response.writeHead(200, {
        "content-type": "application/octet-stream",
        "content-disposition": `attachment; filename*=UTF-8''${encodeURIComponent(`${"文".repeat(100)}.txt`)}`,
      });
      response.end("long");
      return;
    }
    const body = PAGES[path];
    if (body === undefined) {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, { "content-type": "text/html" }).end(body);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address() as NodeNet.AddressInfo;
  return {
    url: `http://127.0.0.1:${address.port}`,
    stop: () =>
      new Promise((resolve) => {
        server.closeAllConnections();
        server.close(() => resolve());
      }),
  };
};
