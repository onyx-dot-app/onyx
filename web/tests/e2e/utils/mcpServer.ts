import { spawn, ChildProcessWithoutNullStreams } from "child_process";
import path from "path";
import net from "net";
import fs from "fs";

interface StartServerOptions {
  host?: string;
  port?: number;
  pythonBinary?: string;
  scriptPath?: string;
  readyTimeoutMs?: number;
}

const DEFAULT_HOST = process.env.MCP_TEST_SERVER_HOST || "127.0.0.1";
const DEFAULT_PORT = Number(process.env.MCP_TEST_SERVER_PORT || "8004");
const READY_TIMEOUT_MS = 25_000;

export class McpServerProcess {
  private process: ChildProcessWithoutNullStreams;
  private host: string;
  private port: number;
  private stopped = false;

  constructor(
    proc: ChildProcessWithoutNullStreams,
    host: string,
    port: number
  ) {
    this.process = proc;
    this.host = host;
    this.port = port;
  }

  get address(): { host: string; port: number } {
    return { host: this.host, port: this.port };
  }

  async stop(signal: NodeJS.Signals = "SIGTERM"): Promise<void> {
    if (this.stopped) return;
    this.stopped = true;
    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        if (!this.process.killed) {
          this.process.kill("SIGKILL");
        }
        resolve();
      }, 5_000);

      this.process.once("exit", () => {
        clearTimeout(timeout);
        resolve();
      });

      this.process.kill(signal);
    });
  }
}

function waitForPort(
  host: string,
  port: number,
  proc: ChildProcessWithoutNullStreams,
  timeoutMs: number
): Promise<void> {
  return new Promise((resolve, reject) => {
    const start = Date.now();

    const check = () => {
      if (proc.exitCode !== null) {
        reject(
          new Error(
            `MCP server process exited with code ${proc.exitCode ?? "unknown"}`
          )
        );
        return;
      }

      const socket = net.createConnection({ host, port });

      socket.once("connect", () => {
        socket.destroy();
        resolve();
      });

      socket.once("error", () => {
        socket.destroy();
        if (Date.now() - start >= timeoutMs) {
          reject(
            new Error(
              `Timed out waiting for MCP OAuth test server to listen on ${host}:${port}`
            )
          );
        } else {
          setTimeout(check, 250);
        }
      });
    };

    check();
  });
}

export async function startMcpOauthServer(
  options: StartServerOptions = {}
): Promise<McpServerProcess> {
  const host = options.host || DEFAULT_HOST;
  const port = options.port ?? DEFAULT_PORT;
  const pythonBinary = options.pythonBinary || "python3";
  const readyTimeout = options.readyTimeoutMs ?? READY_TIMEOUT_MS;

  const scriptPath =
    options.scriptPath ||
    path.resolve(
      __dirname,
      "../../../..",
      "backend/tests/integration/mock_services/mcp_test_server/run_mcp_server_oauth.py"
    );
  const scriptDir = path.dirname(scriptPath);

  const proc = spawn(pythonBinary, [scriptPath, port.toString()], {
    cwd: scriptDir,
    stdio: ["pipe", "pipe", "pipe"],
    env: {
      ...process.env,
      MCP_SERVER_PORT: port.toString(),
      MCP_SERVER_HOST: host,
    },
  });

  proc.stdout.on("data", (chunk) => {
    const message = chunk.toString();
    console.log(`[mcp-oauth-server] ${message.trimEnd()}`);
  });
  proc.stderr.on("data", (chunk) => {
    const message = chunk.toString();
    console.error(`[mcp-oauth-server:stderr] ${message.trimEnd()}`);
  });

  proc.on("error", (err) => {
    console.error("[mcp-oauth-server] failed to start", err);
  });

  await waitForPort(host, port, proc, readyTimeout);

  return new McpServerProcess(proc, host, port);
}
