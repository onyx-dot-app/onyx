"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SvgCheck, SvgCopy, SvgTerminal, SvgTrash } from "@opal/icons";
import { Button, InputTypeIn, Text } from "@opal/components";
import Modal from "@/refresh-components/Modal";
import { useSettings } from "@/lib/settings/hooks";
import { cn } from "@opal/utils";

/**
 * Dev/debug-only button that streams the user's sandbox pod opencode-serve
 * logs in real time. Gated by `opencode_debugging_enabled` in user
 * settings (mirroring `ENABLE_OPENCODE_DEBUGGING` on the backend).
 * Returns null when the flag is off — no DOM, nothing.
 *
 * Modeled after browser devtools / `tail -f`:
 *  - auto-pauses follow when the user scrolls up, resumes on scroll-to-bottom
 *  - substring filter narrows the visible buffer
 *  - severity-coloured rows (INFO neutral, WARN amber, ERROR red)
 *  - status pill with coloured indicator dot
 *  - clear + copy-visible quick actions
 *
 * Client-side ring buffer caps memory at 5k lines.
 */
const LOG_BUFFER_MAX = 2_000;
// Below this many pixels from the bottom edge counts as "at the bottom"
// for follow-mode auto-resume. 32px is one line of slop on most fonts.
const SCROLL_BOTTOM_THRESHOLD_PX = 32;

type StreamStatus = "connecting" | "streaming" | "error" | "closed";

interface LogLine {
  text: string;
  severity: "info" | "warn" | "error" | "other";
  // Stable id for React keys. We can't use line index because the buffer
  // ring-evicts from the head — keys would shift and React would mis-diff.
  id: number;
}

let nextLineId = 1;

function classifySeverity(line: string): LogLine["severity"] {
  // Match common opencode + python log prefixes. Order matters: ERROR is a
  // substring of nothing else here, but we check WARN before WARNING etc.
  if (/\bERROR\b/i.test(line)) return "error";
  if (/\bWARN(?:ING)?\b/i.test(line)) return "warn";
  if (/\bINFO\b/i.test(line)) return "info";
  return "other";
}

interface StatusDotProps {
  status: StreamStatus;
  paused: boolean;
}

function StatusDot({ status, paused }: StatusDotProps) {
  // Resolution order: error > paused > status. A paused-while-streaming bus
  // should read as "paused" not "streaming".
  const color =
    status === "error"
      ? "bg-status-error-05"
      : status === "closed"
        ? "bg-text-03"
        : paused
          ? "bg-status-warning-05"
          : status === "streaming"
            ? "bg-status-success-05"
            : "bg-status-warning-05"; // connecting

  // Halo color for the soft outer ring — same hue, lighter shade, only
  // visible when actively streaming.
  const halo = status === "streaming" && !paused ? "bg-status-success-02" : "";

  // Pulse only while actively streaming. The dot is large enough now
  // (10px) that the pulse animation is actually legible.
  const shouldPulse = status === "streaming" && !paused;
  return (
    <span className="relative inline-flex h-2.5 w-2.5 shrink-0 items-center justify-center">
      {halo && (
        <span
          className={cn(
            "absolute inset-[-3px] rounded-full opacity-60",
            halo,
            shouldPulse && "animate-ping"
          )}
          aria-hidden="true"
        />
      )}
      <span
        className={cn("relative h-2.5 w-2.5 rounded-full", color)}
        aria-hidden="true"
      />
    </span>
  );
}

interface LogStreamPaneProps {
  open: boolean;
}

function LogStreamPane({ open }: LogStreamPaneProps) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [follow, setFollow] = useState<boolean>(true);
  // Lines added while paused — surfaces a "N new since paused" badge so
  // the user knows there's fresh content waiting.
  const [newSincePaused, setNewSincePaused] = useState<number>(0);
  const [filter, setFilter] = useState<string>("");
  const [justCopied, setJustCopied] = useState<boolean>(false);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const copyResetRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Refs mirror the state inside the SSE reader's hot loop without
  // forcing it to re-bind on every state change.
  const followRef = useRef<boolean>(follow);
  followRef.current = follow;

  const appendLine = useCallback((text: string) => {
    const line: LogLine = {
      id: nextLineId++,
      text,
      severity: classifySeverity(text),
    };
    setLines((prev) => {
      if (prev.length < LOG_BUFFER_MAX) return [...prev, line];
      // Drop the oldest 25% in one shot so we don't reallocate on every line.
      const drop = Math.floor(LOG_BUFFER_MAX / 4);
      return [...prev.slice(drop), line];
    });
    if (!followRef.current) {
      setNewSincePaused((n) => n + 1);
    }
  }, []);

  // Connect on open, abort on close.
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus("connecting");
    setLines([]);
    setErrorMessage(null);
    setNewSincePaused(0);

    fetch("/api/build/debug/opencode-logs/stream", {
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
              : response.status === 409
                ? "No running sandbox to tail logs from"
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
                // Backend uses json.dumps which already escapes any real
                // newlines as \n inside the JSON string; JSON.parse
                // decodes them back to real newlines. No client-side
                // replace needed — and doing one would corrupt log lines
                // that contain a literal backslash-n.
                appendLine(payload.line);
              } else if (typeof payload.message === "string") {
                setStatus("error");
                setErrorMessage(payload.message);
              }
            } catch {
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

  // Auto-scroll to bottom when follow=true and lines change.
  useEffect(() => {
    if (!follow) return;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [lines, follow]);

  // Scroll-position-driven follow toggle (the "tail -f" UX).
  // Scrolling up auto-pauses; scrolling back to bottom auto-resumes.
  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const atBottom = distanceFromBottom <= SCROLL_BOTTOM_THRESHOLD_PX;
    if (atBottom && !followRef.current) {
      setFollow(true);
      setNewSincePaused(0);
    } else if (!atBottom && followRef.current) {
      setFollow(false);
    }
  }, []);

  // Filter applies to text; recompute only when filter or lines change.
  const filteredLines = useMemo(() => {
    if (!filter) return lines;
    const needle = filter.toLowerCase();
    return lines.filter((l) => l.text.toLowerCase().includes(needle));
  }, [filter, lines]);

  const handleClear = useCallback(() => {
    setLines([]);
    setNewSincePaused(0);
  }, []);

  const handleCopyVisible = useCallback(async () => {
    const text = filteredLines.map((l) => l.text).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setJustCopied(true);
      if (copyResetRef.current) clearTimeout(copyResetRef.current);
      copyResetRef.current = setTimeout(() => setJustCopied(false), 1500);
    } catch (error) {
      console.error("Failed to copy visible opencode logs", error);
    }
  }, [filteredLines]);

  useEffect(() => {
    return () => {
      if (copyResetRef.current) clearTimeout(copyResetRef.current);
    };
  }, []);

  const handleResumeFollow = useCallback(() => {
    setFollow(true);
    setNewSincePaused(0);
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  return (
    // No vertical gap — the top hairline on LogContent is the separator,
    // and we want toolbar + log to read as one continuous surface (the
    // toolbar being the "chrome" of the terminal it controls).
    <div className="flex flex-col h-full">
      <StatusBar
        status={status}
        paused={!follow}
        errorMessage={errorMessage}
        totalLines={lines.length}
        visibleLines={filteredLines.length}
        newSincePaused={newSincePaused}
        filter={filter}
        onFilterChange={setFilter}
        onClear={handleClear}
        onCopy={handleCopyVisible}
        copyJustSucceeded={justCopied}
        onResume={handleResumeFollow}
      />
      <LogContent
        scrollRef={scrollRef}
        onScroll={onScroll}
        lines={filteredLines}
        empty={
          lines.length === 0
            ? status === "connecting"
              ? "Waiting for the first log line…"
              : status === "error"
                ? (errorMessage ?? "Error")
                : "No lines yet."
            : filter && filteredLines.length === 0
              ? `No lines match "${filter}"`
              : null
        }
      />
    </div>
  );
}

interface StatusBarProps {
  status: StreamStatus;
  paused: boolean;
  errorMessage: string | null;
  totalLines: number;
  visibleLines: number;
  newSincePaused: number;
  filter: string;
  onFilterChange: (v: string) => void;
  onClear: () => void;
  onCopy: () => void;
  copyJustSucceeded: boolean;
  onResume: () => void;
}

function StatusBar({
  status,
  paused,
  errorMessage,
  totalLines,
  visibleLines,
  newSincePaused,
  filter,
  onFilterChange,
  onClear,
  onCopy,
  copyJustSucceeded,
  onResume,
}: StatusBarProps) {
  const filtered = !!filter && visibleLines !== totalLines;
  const stateLabel =
    status === "error"
      ? (errorMessage ?? "Error")
      : status === "closed"
        ? "Closed"
        : status === "connecting"
          ? "Connecting"
          : paused
            ? "Paused"
            : "Streaming";

  // Single-line toolbar: status pill (state + count) on the left, filter
  // input expanding through the middle, action icons on the right. This
  // collapses what was a two-row status+filter layout into one continuous
  // rhythm — matches the density of a devtools panel.
  return (
    <div className="flex items-center gap-3 px-3 py-2">
      <div className="flex items-center gap-2 shrink-0">
        <StatusDot status={status} paused={paused} />
        <Text font="secondary-body" color="text-05" nowrap>
          {stateLabel}
        </Text>
        {status !== "connecting" && status !== "error" && (
          <>
            <span
              className="h-3 w-px bg-border-02 shrink-0"
              aria-hidden="true"
            />
            <Text font="secondary-body" color="text-05" nowrap>
              {filtered
                ? `${visibleLines.toLocaleString()} / ${totalLines.toLocaleString()} lines`
                : `${totalLines.toLocaleString()} lines`}
            </Text>
          </>
        )}
        {paused && newSincePaused > 0 && (
          <button
            type="button"
            onClick={onResume}
            className={cn(
              "rounded-full px-2 py-0.5 text-xs font-medium nowrap",
              "bg-status-warning-01 text-status-warning-05",
              "hover:bg-status-warning-02 transition-colors"
            )}
          >
            +{newSincePaused.toLocaleString()} new · jump
          </button>
        )}
      </div>

      <div className="flex-1 min-w-0">
        <InputTypeIn
          searchIcon
          placeholder="Filter…"
          value={filter}
          onChange={(e) => onFilterChange(e.target.value)}
          clearButton
        />
      </div>

      <div className="flex items-center gap-0.5 shrink-0">
        <Button
          variant="default"
          prominence="tertiary"
          size="sm"
          icon={copyJustSucceeded ? SvgCheck : SvgCopy}
          onClick={onCopy}
          tooltip={copyJustSucceeded ? "Copied" : "Copy visible"}
        />
        <Button
          variant="default"
          prominence="tertiary"
          size="sm"
          icon={SvgTrash}
          onClick={onClear}
          tooltip="Clear"
        />
      </div>
    </div>
  );
}

interface LogContentProps {
  scrollRef: React.MutableRefObject<HTMLDivElement | null>;
  onScroll: () => void;
  lines: LogLine[];
  empty: string | null;
}

function LogContent({ scrollRef, onScroll, lines, empty }: LogContentProps) {
  // The log surface is intentionally the visual focal point: it takes the
  // full body height, sits a half-step darker than the toolbar above it
  // (subtle elevation inversion — terminals are inset, not raised), and
  // is separated by a single top hairline rather than a four-side bordered
  // card. Empty state is plain centered text on the same surface — no
  // nested container — so the "I am a terminal" affordance is preserved
  // even when there's nothing to show.
  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className={cn(
        "flex-1 overflow-auto border-t border-border-02",
        "bg-background-neutral-01 px-4 py-3",
        "font-mono text-xs leading-relaxed"
      )}
    >
      {empty !== null ? (
        <div className="flex h-full items-center justify-center select-none">
          <Text font="secondary-body" color="text-05">
            {empty}
          </Text>
        </div>
      ) : (
        lines.map((line) => <LogRow key={line.id} line={line} />)
      )}
    </div>
  );
}

function LogRow({ line }: { line: LogLine }) {
  // Severity coloring. INFO and "other" use the same neutral tone so the
  // user's eye is only pulled toward WARN/ERROR.
  const colorClass =
    line.severity === "error"
      ? "text-status-error-05"
      : line.severity === "warn"
        ? "text-status-warning-05"
        : "text-text-04";
  return (
    <div className={cn("whitespace-pre-wrap break-all", colorClass)}>
      {line.text || " "}
    </div>
  );
}

interface OpencodeDebugLogsButtonProps {
  folded?: boolean;
}

export default function OpencodeDebugLogsButton({
  folded = false,
}: OpencodeDebugLogsButtonProps) {
  const settings = useSettings();
  const [open, setOpen] = useState(false);

  if (settings.opencode_debugging_enabled !== true) {
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
          <Modal.Content width="xl" height="lg">
            <Modal.Header
              icon={SvgTerminal}
              title="Opencode pod logs"
              description="Live tail of the sandbox container — dev/debug only."
              onClose={() => setOpen(false)}
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
