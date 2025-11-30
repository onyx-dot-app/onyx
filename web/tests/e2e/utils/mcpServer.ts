import { spawn, ChildProcessWithoutNullStreams } from "child_process";
import path from "path";
import net from "net";
import fs from "fs";

interface StartServerOptions {
  bindHost?: string;
  publicHost?: string;
  port?: number;
  pythonBinary?: string;
  scriptPath?: string;
  readyTimeoutMs?: number;
}

const DEFAULT_BIND_HOST =
  process.env.MCP_TEST_SERVER_BIND_HOST ||
  process.env.MCP_TEST_SERVER_HOST ||
  "127.0.0.1";
const DEFAULT_PUBLIC_HOST =
  process.env.MCP_TEST_SERVER_PUBLIC_HOST || DEFAULT_BIND_HOST;
const DEFAULT_PORT = Number(process.env.MCP_TEST_SERVER_PORT || "8004");
const READY_TIMEOUT_MS = 25_000;

export class McpServerProcess {
  private process: ChildProcessWithoutNullStreams;
  private bindHost: string;
  private publicHost: string;
  private port: number;
  private stopped = false;

  constructor(
    proc: ChildProcessWithoutNullStreams,
    bindHost: string,
    publicHost: string,
    port: number
  ) {
    this.process = proc;
    this.bindHost = bindHost;
    this.publicHost = publicHost;
    this.port = port;
  }

  get address(): { host: string; port: number } {
    return { host: this.publicHost, port: this.port };
  }

  get bindAddress(): { host: string; port: number } {
    return { host: this.bindHost, port: this.port };
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

    const connectHost =
      host === "0.0.0.0" || host === "::" ? "127.0.0.1" : host;

    const check = () => {
      if (proc.exitCode !== null) {
        reject(
          new Error(
            `MCP server process exited with code ${proc.exitCode ?? "unknown"}`
          )
        );
        return;
      }

      const socket = net.createConnection({ host: connectHost, port });

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
  const bindHost = options.bindHost || DEFAULT_BIND_HOST;
  const publicHost = options.publicHost || DEFAULT_PUBLIC_HOST;
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
      MCP_SERVER_HOST: bindHost,
      MCP_SERVER_PUBLIC_HOST: publicHost,
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

  await waitForPort(bindHost, port, proc, readyTimeout);

  return new McpServerProcess(proc, bindHost, publicHost, port);
}

export async function startMcpApiKeyServer(
  options: StartServerOptions & { apiKey?: string } = {}
): Promise<McpServerProcess> {
  const bindHost = options.bindHost || DEFAULT_BIND_HOST;
  const publicHost = options.publicHost || DEFAULT_PUBLIC_HOST;
  const port = options.port ?? DEFAULT_PORT;
  const pythonBinary = options.pythonBinary || "python3";
  const readyTimeout = options.readyTimeoutMs ?? READY_TIMEOUT_MS;
  const apiKey = options.apiKey || "test-api-key-12345";

  const scriptPath =
    options.scriptPath ||
    path.resolve(
      __dirname,
      "../../../..",
      "backend/tests/integration/mock_services/mcp_test_server/run_mcp_server_api_key.py"
    );
  const scriptDir = path.dirname(scriptPath);

  const proc = spawn(pythonBinary, [scriptPath, apiKey, port.toString()], {
    cwd: scriptDir,
    stdio: ["pipe", "pipe", "pipe"],
    env: {
      ...process.env,
      MCP_SERVER_PORT: port.toString(),
      MCP_SERVER_HOST: bindHost,
      MCP_SERVER_PUBLIC_HOST: publicHost,
    },
  });

  proc.stdout.on("data", (chunk) => {
    const message = chunk.toString();
    console.log(`[mcp-api-key-server] ${message.trimEnd()}`);
  });
  proc.stderr.on("data", (chunk) => {
    const message = chunk.toString();
    console.error(`[mcp-api-key-server:stderr] ${message.trimEnd()}`);
  });

  proc.on("error", (err) => {
    console.error("[mcp-api-key-server] failed to start", err);
  });

  await waitForPort(bindHost, port, proc, readyTimeout);

  return new McpServerProcess(proc, bindHost, publicHost, port);
}

/**
 * Start the MCP Google OAuth Pass-Through test server.
 *
 * This server validates Google OAuth tokens that are passed through from Onyx.
 * It calls Google's tokeninfo endpoint to verify the token is valid.
 *
 * For testing pass-through OAuth scenarios where Onyx forwards the user's
 * Google OAuth access token to an MCP server.
 */
export async function startMcpGoogleOAuthServer(
  options: StartServerOptions & { requiredScopes?: string[] } = {}
): Promise<McpServerProcess> {
  const bindHost = options.bindHost || DEFAULT_BIND_HOST;
  const publicHost = options.publicHost || DEFAULT_PUBLIC_HOST;
  const port = options.port ?? 8006; // Default to 8006 to not conflict with other MCP servers
  const pythonBinary = options.pythonBinary || "python3";
  const readyTimeout = options.readyTimeoutMs ?? READY_TIMEOUT_MS;
  const requiredScopes = options.requiredScopes || [];

  const scriptPath =
    options.scriptPath ||
    path.resolve(
      __dirname,
      "../../../..",
      "backend/tests/integration/mock_services/mcp_test_server/run_mcp_server_google_oauth.py"
    );
  const scriptDir = path.dirname(scriptPath);

  const proc = spawn(pythonBinary, [scriptPath, port.toString()], {
    cwd: scriptDir,
    stdio: ["pipe", "pipe", "pipe"],
    env: {
      ...process.env,
      MCP_SERVER_PORT: port.toString(),
      MCP_SERVER_HOST: bindHost,
      MCP_SERVER_PUBLIC_HOST: publicHost,
      MCP_GOOGLE_REQUIRED_SCOPES: requiredScopes.join(","),
    },
  });

  proc.stdout.on("data", (chunk) => {
    const message = chunk.toString();
    console.log(`[mcp-google-oauth-server] ${message.trimEnd()}`);
  });
  proc.stderr.on("data", (chunk) => {
    const message = chunk.toString();
    console.error(`[mcp-google-oauth-server:stderr] ${message.trimEnd()}`);
  });

  proc.on("error", (err) => {
    console.error("[mcp-google-oauth-server] failed to start", err);
  });

  await waitForPort(bindHost, port, proc, readyTimeout);

  return new McpServerProcess(proc, bindHost, publicHost, port);
}
