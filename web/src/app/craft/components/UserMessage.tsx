"use client";

// TODO(@raunakab): migrate this `refresh-components/Text` to `@opal/components` Text
import Text from "@/refresh-components/texts/Text";

interface UserMessageProps {
  content: string;
}

export default function UserMessage({ content }: UserMessageProps) {
  return (
    <div className="flex justify-end py-4">
      <div className="max-w-[80%] whitespace-break-spaces rounded-t-16 rounded-bl-16 bg-background-tint-02 py-3 px-4">
        <Text as="p" mainContentBody>
          {content}
        </Text>
      </div>
    </div>
  );
}
