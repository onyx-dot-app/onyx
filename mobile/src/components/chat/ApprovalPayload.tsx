// RN port of web's sections/approvals/PayloadView: one row per top-level argument, muted key and
// value on one baseline. Long strings and large JSON values collapse behind Show more.
import { useState } from "react";
import { ScrollView, View } from "react-native";

import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";

// About three lines at a phone's card width.
const STRING_TRUNCATE_AT = 200;
const JSON_TRUNCATE_AT_LINES = 8;
// web 18rem
const MAX_HEIGHT = 288;

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
  const [expanded, setExpanded] = useState(false);
  return (
    <View className="items-start gap-2">
      <Text
        font={mono ? "secondary-mono" : "secondary-body"}
        color={mono ? "text-04" : "text-05"}
      >
        {isLong && !expanded ? truncated : text}
      </Text>
      {isLong ? (
        <Button
          prominence="tertiary"
          size="sm"
          onPress={() => setExpanded((value) => !value)}
          className="self-end"
        >
          {expanded ? "Show less" : "Show more"}
        </Button>
      ) : null}
    </View>
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

function JsonValue({ value }: { value: unknown }) {
  const full = JSON.stringify(value, null, 2);
  const lines = full.split("\n");
  // Cut at a line boundary so the preview doesn't end mid-token.
  return (
    <ShowMoreValue
      text={full}
      truncated={`${lines.slice(0, JSON_TRUNCATE_AT_LINES).join("\n")}\n…`}
      isLong={lines.length > JSON_TRUNCATE_AT_LINES}
      mono
    />
  );
}

function PayloadValue({ value }: { value: unknown }) {
  if (typeof value === "string") return <StringValue text={value} />;
  if (typeof value === "number" || typeof value === "boolean") {
    return (
      <Text font="secondary-body" color="text-05">
        {String(value)}
      </Text>
    );
  }
  // Primitive arrays read as one comma-joined line; other arrays stay JSON.
  if (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every(
      (item) =>
        typeof item === "string" ||
        typeof item === "number" ||
        typeof item === "boolean",
    )
  ) {
    return <StringValue text={value.map(String).join(", ")} />;
  }
  return <JsonValue value={value} />;
}

export function ApprovalPayload({
  payload,
}: {
  payload: Record<string, unknown>;
}) {
  // RN has no grid; the key column takes the widest measured key, up to 40% of the row.
  const [keyWidth, setKeyWidth] = useState(0);
  const entries = Object.entries(payload).filter(
    ([, value]) => value !== null && value !== undefined,
  );
  if (entries.length === 0) {
    return (
      <Text font="secondary-body" color="text-03">
        No payload.
      </Text>
    );
  }
  return (
    <ScrollView style={{ maxHeight: MAX_HEIGHT }} nestedScrollEnabled>
      <View className="gap-4">
        {entries.map(([key, value]) => (
          <View key={key} className="flex-row items-baseline gap-12">
            <View
              className="max-w-[40%]"
              style={keyWidth > 0 ? { width: keyWidth } : undefined}
            >
              <Text
                font="secondary-body"
                color="text-03"
                maxLines={1}
                className="self-start"
                onLayout={(event) => {
                  const width = Math.ceil(event.nativeEvent.layout.width);
                  setKeyWidth((current) => Math.max(current, width));
                }}
              >
                {key}
              </Text>
            </View>
            <View className="min-w-0 flex-1">
              <PayloadValue value={value} />
            </View>
          </View>
        ))}
      </View>
    </ScrollView>
  );
}
