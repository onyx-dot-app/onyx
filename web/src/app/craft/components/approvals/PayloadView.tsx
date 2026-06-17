"use client";

import { Fragment, useState } from "react";

import { Button, Text } from "@opal/components";
import { cn } from "@opal/utils";

interface PayloadViewProps {
  payload: Record<string, unknown>;
}

// Past this length a string value renders with Show more / Show less.
// Sized to fit ~3 lines at the approval card's typical width.
const STRING_TRUNCATE_AT = 300;

// Past this many lines a pretty-printed JSON value renders with Show
// more. Sized to keep small nested objects fully visible while
// truncating anything that would dominate the inset.
const JSON_TRUNCATE_AT_LINES = 8;

/**
 * Inset card that frames every payload display. Sits inside the
 * ApprovalCard's outer border on a slightly tinted background so the
 * payload reads as a distinct content region, not a continuation of
 * the card chrome.
 */
function InsetBlock({ children }: { children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "rounded-08 border-[0.5px] overflow-hidden px-3 py-2 max-h-[18rem] overflow-y-auto",
        "bg-background-neutral-01 border-border-01"
      )}
    >
      {children}
    </div>
  );
}

function StringValue({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const needsTruncation = text.length > STRING_TRUNCATE_AT && !expanded;
  const shown = needsTruncation
    ? `${text.slice(0, STRING_TRUNCATE_AT)}…`
    : text;
  return (
    <div className="flex flex-col gap-1 items-start">
      <div className="whitespace-pre-wrap wrap-break-word">
        <Text font="main-ui-body" color="text-05">
          {shown}
        </Text>
      </div>
      {text.length > STRING_TRUNCATE_AT && (
        <div className="self-end">
          <Button
            prominence="tertiary"
            size="sm"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "Show less" : "Show more"}
          </Button>
        </div>
      )}
    </div>
  );
}

function NestedJsonValue({ value }: { value: unknown }) {
  const [expanded, setExpanded] = useState(false);
  const full = JSON.stringify(value, null, 2);
  const lines = full.split("\n");
  const isLong = lines.length > JSON_TRUNCATE_AT_LINES;
  const needsTruncation = isLong && !expanded;
  // Truncate at a line boundary so the preview doesn't end mid-token.
  // The "…" line gives a visual cue that more is hidden.
  const shown = needsTruncation
    ? `${lines.slice(0, JSON_TRUNCATE_AT_LINES).join("\n")}\n…`
    : full;
  return (
    <div className="flex flex-col gap-1 items-start">
      <div className="whitespace-pre-wrap wrap-break-word">
        <Text as="p" font="secondary-mono" color="text-04">
          {shown}
        </Text>
      </div>
      {isLong && (
        <div className="self-end">
          <Button
            prominence="tertiary"
            size="sm"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "Show less" : "Show more"}
          </Button>
        </div>
      )}
    </div>
  );
}

/**
 * Routes a single payload value to the right renderer based on its
 * runtime type. Kept exhaustive so adding a new branch (e.g. dates) is
 * a single edit.
 */
function StructuredValue({ value }: { value: unknown }) {
  if (typeof value === "string") {
    return <StringValue text={value} />;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return (
      <Text font="main-ui-body" color="text-05">
        {String(value)}
      </Text>
    );
  }
  if (Array.isArray(value)) {
    // Empty arrays go through JSON so they render as `[]` (matching
    // how empty objects render)
    if (value.length === 0) {
      return <NestedJsonValue value={value} />;
    }
    // Arrays of primitives flatten to a comma-joined line; arrays of
    // objects fall through to JSON so per-object structure stays
    // legible.
    const allPrimitive = value.every(
      (v) =>
        typeof v === "string" || typeof v === "number" || typeof v === "boolean"
    );
    if (allPrimitive) {
      // Route through StringValue so a very long comma-joined list
      // gets the same Show more treatment as a long string.
      return <StringValue text={value.map((v) => String(v)).join(", ")} />;
    }
    return <NestedJsonValue value={value} />;
  }
  if (typeof value === "object" && value !== null) {
    return <NestedJsonValue value={value} />;
  }
  // null / undefined are filtered out at the entries level, so we
  // shouldn't land here. Render nothing if we do.
  return null;
}

/**
 * Walks the top-level keys of a payload and renders each as a labelled
 * row. Heuristics by value type — short strings inline, long strings
 * with Show more, primitives as-is, nested objects and arrays of
 * objects fall back to pretty-printed JSON.
 */
function StructuredPayloadView({
  payload,
}: {
  payload: Record<string, unknown>;
}) {
  const entries = Object.entries(payload).filter(
    ([, v]) => v !== null && v !== undefined
  );
  if (entries.length === 0) {
    return (
      <InsetBlock>
        <Text font="secondary-body" color="text-03">
          No payload.
        </Text>
      </InsetBlock>
    );
  }
  return (
    <InsetBlock>
      {/*
       * CSS grid so the key column auto-sizes to the widest key across
       * all rows. A flex layout would only align widths row-by-row,
       * making each row's key column independent.
       *
       * The 10rem cap prevents one unusually long key (e.g.
       * `external_user_reference_id`) from eating most of the row.
       * Keys over the cap render with a CSS ellipsis; the native
       * `title` attribute below surfaces the full key on hover.
       */}
      <div className="grid grid-cols-[minmax(5rem,10rem)_1fr] gap-x-3 gap-y-2">
        {entries.map(([key, value]) => (
          <Fragment key={key}>
            <div className="pt-0.5 min-w-0 truncate" title={key}>
              <Text font="secondary-body" color="text-03">
                {key}
              </Text>
            </div>
            <div className="min-w-0">
              <StructuredValue value={value} />
            </div>
          </Fragment>
        ))}
      </div>
    </InsetBlock>
  );
}

export default function PayloadView({ payload }: PayloadViewProps) {
  return <StructuredPayloadView payload={payload} />;
}
