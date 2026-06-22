"use client";

import "@opal/components/end-of-list/styles.css";
import { Text } from "@opal/components";
import type { RichStr } from "@opal/types";

interface EndOfListProps {
  title: string | RichStr;
}

function EndOfList({ title }: EndOfListProps) {
  return (
    <div className="opal-end-of-list">
      <div className="opal-end-of-list-line" />
      <Text font="secondary-body" color="text-03" nowrap>
        {title}
      </Text>
      <div className="opal-end-of-list-line" />
    </div>
  );
}

export { EndOfList, type EndOfListProps };
