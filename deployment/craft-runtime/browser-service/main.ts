import * as NodeFSP from "node:fs/promises";
import * as NodeNet from "node:net";
import { chromium } from "playwright-core";
import { BrowserService } from "./src/service.ts";
import type { Log } from "./src/service.ts";

const log: Log = (event, fields = {}) => {
  process.stderr.write(`${JSON.stringify({ time: new Date().toISOString(), event, ...fields })}\n`);
};

const required = (name: string) => {
  const value = process.env[name];
  if (!value) {
    log("missing_env", { name });
    process.exit(2);
  }
  return value;
};

const main = async () => {
  if (process.argv.includes("--check")) {
    if (typeof chromium.connectOverCDP !== "function") throw new Error("playwright-core is broken");
    process.stdout.write("browser-service ok\n");
    return;
  }
  const cdpUrl = required("ONYX_BROWSER_CDP_URL");
  const socketPath = required("ONYX_BROWSER_SOCKET");
  const sessionsRoot = required("ONYX_SESSIONS_ROOT");

  // One page must never take the process down; log and keep serving.
  process.on("unhandledRejection", (reason) => log("unhandled_rejection", { error: String(reason) }));
  process.on("uncaughtException", (error) =>
    log("uncaught_exception", { error: String(error), stack: error.stack?.split("\n").slice(0, 5).join(" | ") }),
  );

  const browser = await chromium.connectOverCDP(cdpUrl);
  const context = browser.contexts()[0];
  if (!context) {
    log("no_default_context");
    process.exit(1);
  }
  browser.on("disconnected", () => {
    log("browser_disconnected");
    process.exit(1);
  });
  const service = new BrowserService({ context, sessionsRoot, log });
  service.start();

  await NodeFSP.rm(socketPath, { force: true });
  const server = NodeNet.createServer({ allowHalfOpen: true }, (socket) => service.handleConnection(socket));
  server.on("error", (error) => {
    log("server_error", { error: error.message });
    process.exit(1);
  });
  await new Promise<void>((resolve) => server.listen(socketPath, resolve));
  await NodeFSP.chmod(socketPath, 0o600);
  log("listening", { socket: socketPath, cdp: cdpUrl });

  const stop = (signal: string) => {
    log("stopping", { signal });
    server.close();
    void NodeFSP.rm(socketPath, { force: true }).finally(() => process.exit(0));
  };
  process.on("SIGTERM", () => stop("SIGTERM"));
  process.on("SIGINT", () => stop("SIGINT"));
};

main().catch((error: unknown) => {
  log("fatal", { error: String(error) });
  process.exit(1);
});
