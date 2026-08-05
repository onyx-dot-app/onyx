"use client";

import "@opal/components/end-of-list/styles.css";
import { Divider, Text } from "@opal/components";
import type { RichStr } from "@opal/types";

interface EndOfListProps {
  title: string | RichStr;
}

function EndOfList({ title }: EndOfListProps) {
  return (
    <div className="opal-end-of-list">
      <Divider paddingParallel="fit" paddingPerpendicular="fit" />
      <Text font="secondary-body" color="text-03" nowrap>
        {title}
      </Text>
      <Divider paddingParallel="fit" paddingPerpendicular="fit" />
    </div>
  );
}

export { EndOfList, type EndOfListProps };
