"use client";

import { useState } from "react";

import { Button, Text } from "@opal/components";
import { cn } from "@opal/utils";

interface PayloadViewProps {
  actionType: string;
  payload: Record<string, unknown>;
}

const SLACK_BODY_TRUNCATE_AT = 300;

interface SlackSendMessagePayload {
  channel: string;
  text: string;
}

function isSlackSendMessagePayload(
  payload: Record<string, unknown>
): payload is Record<string, unknown> & SlackSendMessagePayload {
  return (
    typeof payload.channel === "string" &&
    payload.channel.length > 0 &&
    typeof payload.text === "string"
  );
}

/**
 * Code-block surface for the JSON fallback. Matches the styling of
 * tool-card bodies (BashBody/SearchBody/etc.) so payload previews read
 * as a sibling to the tool output above them.
 */
function JsonBlock({ value }: { value: unknown }) {
  return (
    <div
      className={cn(
        "rounded-08 border-[0.5px] overflow-hidden px-3 py-2 max-h-[18rem] overflow-y-auto",
        "bg-background-neutral-01 border-border-01",
        "whitespace-pre-wrap wrap-break-word"
      )}
    >
      <Text as="p" font="secondary-mono" color="text-04">
        {JSON.stringify(value, null, 2)}
      </Text>
    </div>
  );
}

function MalformedNotice() {
  return (
    <Text font="secondary-body" color="text-03">
      Payload did not match expected shape.
    </Text>
  );
}

function SlackSendMessageView({
  payload,
}: {
  payload: SlackSendMessagePayload;
}) {
  const [expanded, setExpanded] = useState(false);
  const body = payload.text;
  const needsTruncation = body.length > SLACK_BODY_TRUNCATE_AT && !expanded;
  const shown = needsTruncation
    ? `${body.slice(0, SLACK_BODY_TRUNCATE_AT)}…`
    : body;

  return (
    <div className="flex flex-col gap-1">
      <Text font="secondary-body" color="text-03">
        Channel
      </Text>
      <Text font="main-ui-body" color="text-05">
        {payload.channel}
      </Text>
      <Text font="secondary-body" color="text-03">
        Message
      </Text>
      <Text font="main-ui-body" color="text-05">
        {shown}
      </Text>
      {body.length > SLACK_BODY_TRUNCATE_AT && (
        <div className="self-start">
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

export default function PayloadView({ actionType, payload }: PayloadViewProps) {
  switch (actionType) {
    case "slack.send_message": {
      if (!isSlackSendMessagePayload(payload)) {
        return (
          <div className="flex flex-col gap-2">
            <MalformedNotice />
            <JsonBlock value={payload} />
          </div>
        );
      }
      return <SlackSendMessageView payload={payload} />;
    }
    default:
      return <JsonBlock value={payload} />;
  }
}
