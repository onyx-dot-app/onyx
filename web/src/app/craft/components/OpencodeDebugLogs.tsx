"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { SvgTerminal } from "@opal/icons";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import Modal from "@/refresh-components/Modal";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { cn } from "@opal/utils";

/**
 * Dev/debug-only button that streams the user's sandbox pod opencode-serve
 * logs in real time. Gated by the `opencode_debugging_enabled` flag in user
 * settings (which mirrors the `ENABLE_OPENCODE_DEBUGGING` env var on the
 * backend). Returns null when the flag is off — no DOM, no button, nothing.
 *
 * The streaming pane buffers up to LOG_BUFFER_MAX lines client-side so a
 * long-running tail doesn't slowly eat browser memory.
 */
const LOG_BUFFER_MAX = 5_000;

function ScrollToBottomToggle({
  follow,
  setFollow,
}: ScrollToBottomToggleProps) {
  return (
    <Button
      variant="default"
      prominence={follow ? "primary" : "tertiary"}
      size="sm"
      onClick={() => setFollow((f) => !f)}
    >
      {follow ? "Following" : "Paused"}
    </Button>
  );
}

interface ScrollToBottomToggleProps {
  follow: boolean;
  setFollow: React.Dispatch<React.SetStateAction<boolean>>;
}

interface LogStreamPaneProps {
  open: boolean;
}

function LogStreamPane({ open }: LogStreamPaneProps) {
  const [lines, setLines] = useState<string[]>([]);
  const [status, setStatus] = useState<
    "connecting" | "streaming" | "error" | "closed"
  >("connecting");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [follow, setFollow] = useState<boolean>(true);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const appendLine = useCallback((line: string) => {
    setLines((prev) => {
      if (prev.length < LOG_BUFFER_MAX) return [...prev, line];
      // Drop the oldest 25% in one shot so we don't reallocate on every line.
      const drop = Math.floor(LOG_BUFFER_MAX / 4);
      return [...prev.slice(drop), line];
    });
  }, []);

  // Connect on open, abort on close. Re-connecting (via close+reopen) is
  // intentional — it lets the user reset the buffer + re-grab the
  // tail_lines=200 history snapshot from the backend.
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus("connecting");
    setLines([]);
    setErrorMessage(null);

    const url = "/api/build/debug/opencode-logs/stream";
    fetch(url, {
      method: "GET",
      headers: { Accept: "text/event-stream" },
      signal: controller.signal,
      credentials: "same-origin",
    })
      .then(async (response) => {
        if (!response.ok || !response.body) {
          setStatus("error");
          setErrorMessage(
            response.status === 404
              ? "Debug endpoint disabled (ENABLE_OPENCODE_DEBUGGING=false)"
              : `HTTP ${response.status}`
          );
          return;
        }
        setStatus("streaming");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            setStatus("closed");
            break;
          }
          buf += decoder.decode(value, { stream: true });
          let nl: number;
          while ((nl = buf.indexOf("\n\n")) !== -1) {
            const block = buf.slice(0, nl);
            buf = buf.slice(nl + 2);
            const dataLine = block
              .split("\n")
              .find((l) => l.startsWith("data:"));
            if (!dataLine) continue;
            try {
              const payload = JSON.parse(dataLine.slice(5).trim());
              if (typeof payload.line === "string") {
                appendLine(payload.line.replace(/\\n/g, "\n"));
              } else if (typeof payload.message === "string") {
                setStatus("error");
                setErrorMessage(payload.message);
              }
            } catch {
              // Malformed event — surface a readable warning rather than
              // silently dropping (helps when the backend changes shape).
              appendLine(`[debug-stream] dropped malformed frame: ${block}`);
            }
          }
        }
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        setStatus("error");
        setErrorMessage(String(err));
      });

    return () => {
      controller.abort();
      abortRef.current = null;
    };
  }, [open, appendLine]);

  // Auto-scroll to bottom on new lines when follow=true.
  useEffect(() => {
    if (!follow) return;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [lines, follow]);

  const statusLabel: Record<typeof status, string> = {
    connecting: "Connecting…",
    streaming: `Streaming (${lines.length} lines)`,
    error: errorMessage ?? "Error",
    closed: "Stream closed",
  };

  return (
    <div className="flex flex-col h-full gap-2">
      <div className="flex items-center justify-between px-2">
        <Text secondaryBody>{statusLabel[status]}</Text>
        <ScrollToBottomToggle follow={follow} setFollow={setFollow} />
      </div>
      <div
        ref={scrollRef}
        className={cn(
          "flex-1 overflow-auto rounded-md border border-border-02",
          "bg-background-neutral-01 px-3 py-2 font-mono text-xs leading-tight"
        )}
      >
        {lines.length === 0 && status === "connecting" && (
          <Text secondaryBody>Waiting for first log line…</Text>
        )}
        {lines.map((line, i) => (
          <div key={i} className="whitespace-pre-wrap break-all text-text-04">
            {line || " "}
          </div>
        ))}
      </div>
    </div>
  );
}

interface OpencodeDebugLogsButtonProps {
  folded?: boolean;
}

export default function OpencodeDebugLogsButton({
  folded = false,
}: OpencodeDebugLogsButtonProps) {
  const settings = useSettingsContext();
  const [open, setOpen] = useState(false);

  if (settings?.settings?.opencode_debugging_enabled !== true) {
    return null;
  }

  return (
    <>
      <Button
        variant="default"
        prominence="tertiary"
        size="sm"
        icon={SvgTerminal}
        onClick={() => setOpen(true)}
      >
        {folded ? "" : "Pod logs"}
      </Button>
      {open && (
        <Modal open onOpenChange={(o) => !o && setOpen(false)}>
          <Modal.Content width="lg" height="lg">
            <Modal.Header
              icon={SvgTerminal}
              title="Opencode pod logs"
              description="Live tail of the sandbox container — dev/debug only."
            />
            <Modal.Body>
              <LogStreamPane open={open} />
            </Modal.Body>
          </Modal.Content>
        </Modal>
      )}
    </>
  );
}
