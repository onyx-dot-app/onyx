"use client";

import { useEffect, useRef, useState } from "react";
import { Text, Button, CopyButton } from "@opal/components";
import { SvgChevronDown } from "@opal/icons";
import { Hoverable } from "@opal/core";

const COLLAPSED_MAX_PX = 240; // ~10 lines

interface UserMessageProps {
  content: string;
}

function ClampedContent({ content }: { content: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (el) setOverflows(el.scrollHeight > COLLAPSED_MAX_PX + 8);
  }, [content]);

  return (
    <div className="flex flex-col items-start gap-1">
      <div
        ref={ref}
        className="relative w-full overflow-hidden"
        style={expanded ? undefined : { maxHeight: COLLAPSED_MAX_PX }}
      >
        <Text as="p" font="main-content-body" color="text-04">
          {content}
        </Text>
        {!expanded && overflows && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-linear-to-b from-transparent to-background-tint-02" />
        )}
      </div>
      {overflows && (
        <Button
          variant="default"
          prominence="tertiary"
          size="2xs"
          icon={SvgChevronDown}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Show less" : "Show more"}
        </Button>
      )}
    </div>
  );
}

export default function UserMessage({ content }: UserMessageProps) {
  return (
    <Hoverable.Root group="craftUserMessage" width="full">
      <div className="flex items-start justify-end gap-1 py-4">
        <Hoverable.Item group="craftUserMessage" variant="appear-on-hover">
          <CopyButton
            getCopyText={() => content}
            prominence="tertiary"
            data-testid="CraftUserMessage/copy-button"
          />
        </Hoverable.Item>
        <div className="max-w-[80%] whitespace-break-spaces rounded-t-16 rounded-bl-16 bg-background-tint-02 py-3 px-4">
          <ClampedContent content={content} />
        </div>
      </div>
    </Hoverable.Root>
  );
}
