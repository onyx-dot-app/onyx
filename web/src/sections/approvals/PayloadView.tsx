"use client";

import { Fragment, useState } from "react";
import { useTranslations } from "next-intl";

import { Button, Text } from "@opal/components";
import { Section } from "@opal/layouts";

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

function ShowMoreValue({
  text,
  truncated,
  isLong,
  mono,
}: {
  text: string;
  truncated: string;
  isLong: boolean;
  mono: boolean;
}) {
  const t = useTranslations("common.payloadView");
  const [expanded, setExpanded] = useState(false);
  return (
    <Section gap={0.5} alignItems="start" height="auto">
      <div className="min-w-0 whitespace-pre-wrap wrap-anywhere">
        <Text
          as="p"
          font={mono ? "secondary-mono" : "secondary-body"}
          color={mono ? "text-04" : "text-05"}
        >
          {isLong && !expanded ? truncated : text}
        </Text>
      </div>
      {isLong && (
        <Section alignItems="end" height="auto">
          <Button
            prominence="tertiary"
            size="sm"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? t("showLess.button") : t("showMore.button")}
          </Button>
        </Section>
      )}
    </Section>
  );
}

function StringValue({ text }: { text: string }) {
  return (
    <ShowMoreValue
      text={text}
      truncated={`${text.slice(0, STRING_TRUNCATE_AT)}…`}
      isLong={text.length > STRING_TRUNCATE_AT}
      mono={false}
    />
  );
}

function NestedJsonValue({ value }: { value: unknown }) {
  const full = JSON.stringify(value, null, 2);
  const lines = full.split("\n");
  // Truncate at a line boundary so the preview doesn't end mid-token.
  return (
    <ShowMoreValue
      text={full}
      truncated={`${lines.slice(0, JSON_TRUNCATE_AT_LINES).join("\n")}\n…`}
      isLong={lines.length > JSON_TRUNCATE_AT_LINES}
      mono
    />
  );
}

/** Routes a single payload value to the right renderer by its runtime type. */
function StructuredValue({ value }: { value: unknown }) {
  if (typeof value === "string") {
    return <StringValue text={value} />;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return (
      <Text as="p" font="secondary-body" color="text-05">
        {String(value)}
      </Text>
    );
  }
  if (Array.isArray(value)) {
    // Arrays of primitives flatten to a comma-joined line; empty arrays and
    // arrays of objects fall through to JSON so structure stays legible.
    const allPrimitive =
      value.length > 0 &&
      value.every(
        (v) =>
          typeof v === "string" ||
          typeof v === "number" ||
          typeof v === "boolean"
      );
    if (allPrimitive) {
      return <StringValue text={value.map((v) => String(v)).join(", ")} />;
    }
    return <NestedJsonValue value={value} />;
  }
  if (typeof value === "object" && value !== null) {
    return <NestedJsonValue value={value} />;
  }
  return null;
}

/**
 * Renders each top-level key of a payload as a labelled row. Short strings
 * show inline, long strings and large JSON values get Show more, and nested
 * objects render as pretty-printed JSON.
 */
export default function PayloadView({ payload }: PayloadViewProps) {
  const t = useTranslations("common.payloadView");
  const entries = Object.entries(payload).filter(
    ([, v]) => v !== null && v !== undefined
  );
  if (entries.length === 0) {
    return (
      <Text font="secondary-body" color="text-03">
        {t("empty.label")}
      </Text>
    );
  }
  return (
    // The key column sizes to the widest key, up to 10rem; a longer key is
    // cut and shows in full in a tooltip.
    <dl className="m-0 grid max-h-[18rem] grid-cols-[minmax(0,max-content)_minmax(0,1fr)] items-baseline gap-x-3 gap-y-1 overflow-y-auto">
      {entries.map(([key, value]) => (
        <Fragment key={key}>
          <dt className="max-w-40 min-w-0">
            <Text
              as="p"
              font="secondary-body"
              color="text-03"
              maxLines={1}
              overflowTooltip
            >
              {key}
            </Text>
          </dt>
          <dd className="m-0 min-w-0">
            <StructuredValue value={value} />
          </dd>
        </Fragment>
      ))}
    </dl>
  );
}
