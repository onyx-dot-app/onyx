// Failures are returned as observations, never thrown; a thrown tool error
// would abort the agent's turn instead of letting it recover.
//
// Module resolution: this file lives in /workspace/opencode-plugins, which
// has no node_modules, so a bare runtime `import` of the SDK can't resolve.
// The type import is erased; the `tool` helper is loaded at runtime by
// absolute path from opencode's bundled SDK (same approach as connect-app.ts).

import type { Plugin } from "@opencode-ai/plugin";
import type { tool as ToolFactory } from "@opencode-ai/plugin/tool";
import { spawn } from "node:child_process";
import { constants as fsConstants } from "node:fs";
import { access, readFile } from "node:fs/promises";

const SDK_TOOL_PATHS = [
  "/home/sandbox/.opencode/node_modules/@opencode-ai/plugin/dist/tool.js",
  "/home/sandbox/.config/opencode/node_modules/@opencode-ai/plugin/dist/tool.js",
];

async function loadToolFactory(): Promise<typeof ToolFactory> {
  for (const path of SDK_TOOL_PATHS) {
    try {
      return (await import(path)).tool;
    } catch {
      continue;
    }
  }
  throw new Error("could not resolve the @opencode-ai/plugin tool helper");
}

const SCRIPT_REL = "start-webapp.sh";
const PID_REL = "nextjs.pid";
const LOG_REL = "nextjs.log";
const APP_DIR_REL = "outputs/web";

const DEFAULT_ACTION_LOG_LINES = 10;
const DEFAULT_LOGS_LINES = 30;
const MAX_LOG_LINES = 200;
const START_TIMEOUT_MS = 150_000;
const MAX_OUTPUT_BYTES = 8 * 1024;
const PROBE_TIMEOUT_MS = 2000;

async function pathExists(path: string): Promise<boolean> {
  try {
    await access(path, fsConstants.F_OK);
    return true;
  } catch {
    return false;
  }
}

async function resolveScript(dir: string): Promise<string | null> {
  const scriptPath = `${dir}/${SCRIPT_REL}`;
  return (await pathExists(scriptPath)) ? scriptPath : null;
}

function parsePort(scriptText: string): number | null {
  const match = scriptText.match(/^PORT=(\d+)$/m);
  return match ? parseInt(match[1], 10) : null;
}

async function pidAlive(dir: string): Promise<number | null> {
  const pidPath = `${dir}/${PID_REL}`;
  if (!(await pathExists(pidPath))) return null;
  const pid = parseInt((await readFile(pidPath, "utf8")).trim(), 10);
  if (!Number.isFinite(pid)) return null;
  try {
    process.kill(pid, 0);
    return pid;
  } catch {
    return null;
  }
}

async function probeRunning(port: number): Promise<boolean> {
  try {
    await fetch(`http://127.0.0.1:${port}/`, {
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    });
    return true;
  } catch {
    return false;
  }
}

async function tailLog(dir: string, n: number): Promise<string | null> {
  const logPath = `${dir}/${LOG_REL}`;
  if (!(await pathExists(logPath))) return null;
  const lines = (await readFile(logPath, "utf8")).split("\n");
  if (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
  return lines.slice(-n).join("\n");
}

interface Observation {
  state: "running" | "not_running";
  port: number | null;
  text: string;
}

async function buildObservation(
  dir: string,
  scriptPath: string,
  logLines: number
): Promise<Observation> {
  const scriptText = await readFile(scriptPath, "utf8");
  const port = parsePort(scriptText);
  const pid = await pidAlive(dir);
  const running = pid !== null && port !== null && (await probeRunning(port));
  const state: Observation["state"] = running ? "running" : "not_running";
  const isScaffolded = await pathExists(`${dir}/${APP_DIR_REL}/package.json`);

  const lines = [
    `state: ${state}`,
    port !== null
      ? `port: ${port}`
      : "port: unknown (could not parse PORT from start-webapp.sh)",
    `app dir: ${APP_DIR_REL}`,
    `scaffolded: ${isScaffolded ? "yes" : "no"}`,
    `logs: ${LOG_REL}`,
  ];

  const cappedLines = Math.min(logLines, MAX_LOG_LINES);
  const tail = await tailLog(dir, cappedLines);
  if (tail) {
    lines.push(`--- last ${cappedLines} lines of ${LOG_REL} ---`, tail);
  }

  return { state, port, text: lines.join("\n") };
}

function runScript(
  dir: string,
  scriptPath: string,
  abort: AbortSignal
): Promise<{ exitCode: number; output: string }> {
  return new Promise((resolve) => {
    const quotedPath = `'${scriptPath.replace(/'/g, `'\\''`)}'`;
    const child = spawn("bash", ["-c", `bash ${quotedPath} 2>&1`], {
      cwd: dir,
      signal: abort,
    });

    let output = "";
    child.stdout?.on("data", (chunk: Buffer) => {
      output += chunk.toString("utf8");
    });

    const timeoutId = setTimeout(() => child.kill(), START_TIMEOUT_MS);
    const finish = (exitCode: number) => {
      clearTimeout(timeoutId);
      if (output.length > MAX_OUTPUT_BYTES) {
        output = output.slice(-MAX_OUTPUT_BYTES);
      }
      resolve({ exitCode, output });
    };

    child.on("close", (code) => finish(code ?? 1));
    child.on("error", () => finish(1));
  });
}

const UNAVAILABLE_OBSERVATION =
  "state: unavailable\n" +
  "this session has no web-app support (headless session) or the bootstrap " +
  "script was deleted; reopen the session to regenerate it; never run " +
  "`bun run dev` yourself.";

export const Webapp: Plugin = async () => {
  const tool = await loadToolFactory();

  return {
    tool: {
      webapp: tool({
        description:
          "Manage this session's web-app dev server. Call with action='start' " +
          "BEFORE building a web app: it scaffolds outputs/web, installs " +
          "dependencies, starts the dev server, and waits until it serves. " +
          "SAFE TO CALL REPEATEDLY: it reconciles current state (already " +
          "running = success, crashed = restarted). Use action='status' or " +
          "'logs' to diagnose problems, and action='restart' if the server is " +
          "up but misbehaving. NEVER run `bun run dev` or start your own " +
          "server; the preview proxy only routes to the port this tool manages.",
        args: {
          action: tool.schema
            .enum(["start", "status", "logs", "restart"])
            .describe(
              "start: scaffold/install/start the dev server and wait for it " +
                "to become ready (idempotent - safe even if already running). " +
                "status: report whether the server is running, without " +
                "starting anything. logs: show a larger log tail for " +
                "debugging. restart: stop the current server (if any) and " +
                "start it again - use when it's up but misbehaving."
            ),
          lines: tool.schema
            .number()
            .optional()
            .describe(
              "Log lines to include, default 30, max 200 - only meaningful " +
                "for action='logs'."
            ),
        },
        async execute(args, context) {
          const dir = context.directory;
          const titles: Record<string, string> = {
            start: "Starting web app…",
            restart: "Restarting web app…",
            status: "Checking web app status…",
            logs: "Reading web app logs…",
          };
          context.metadata({ title: titles[args.action] });

          const scriptPath = await resolveScript(dir);
          if (!scriptPath) {
            return UNAVAILABLE_OBSERVATION;
          }

          if (args.action === "status") {
            const obs = await buildObservation(dir, scriptPath, DEFAULT_ACTION_LOG_LINES);
            const headline =
              obs.state === "running"
                ? `web app is running on port ${obs.port} and the preview updates live (hot reload)`
                : "web app is not running; call webapp start";
            return `${headline}\n\n${obs.text}`;
          }

          if (args.action === "logs") {
            const n = Math.min(args.lines ?? DEFAULT_LOGS_LINES, MAX_LOG_LINES);
            const obs = await buildObservation(dir, scriptPath, n);
            const headline =
              obs.state === "running"
                ? `web app is running on port ${obs.port}`
                : "web app is not running";
            return `${headline}\n\n${obs.text}`;
          }

          if (args.action === "restart") {
            const pid = await pidAlive(dir);
            if (pid !== null) {
              try {
                process.kill(pid);
              } catch {}
              await new Promise((r) => setTimeout(r, 2000));
            }
          }

          const { exitCode, output } = await runScript(dir, scriptPath, context.abort);
          const obs = await buildObservation(dir, scriptPath, DEFAULT_ACTION_LOG_LINES);

          // The port is the proxy's routing contract (DB-allocated):
          // port_conflict must never auto-heal onto another port; a moved
          // server would "run" but be unreachable via the preview.
          let headline: string;
          let errorKind: string | null = null;
          if (exitCode === 0) {
            headline = output.includes("already running")
              ? "webapp was already running"
              : "webapp started successfully";
          } else if (
            output.includes("EADDRINUSE") ||
            output.includes("address already in use")
          ) {
            errorKind = "port_conflict";
            headline =
              "webapp start failed: something else is bound to the managed " +
              `port${obs.port !== null ? ` ${obs.port}` : ""}. Kill that ` +
              "process (e.g. `fuser -k <port>/tcp`), then call webapp start " +
              "again. Do not start a server on a different port; the " +
              "preview proxy only routes to the managed port.";
          } else if (output.includes("did not become ready")) {
            errorKind = "app_boot_failure";
            headline =
              "webapp start failed: the server did not become ready. the " +
              "server crashed or the app code throws on boot; read the log " +
              "tail, fix the code, then call webapp start again.";
          } else {
            errorKind = "bootstrap_failure";
            headline =
              "webapp start failed. fix the error shown above, then call " +
              "webapp start again.";
          }

          const errorKindLine = errorKind ? `error_kind: ${errorKind}\n` : "";
          return (
            `${headline}\n\n` +
            `--- script output ---\n${output}\n\n${errorKindLine}${obs.text}`
          );
        },
      }),
    },
  };
};

export default Webapp;
