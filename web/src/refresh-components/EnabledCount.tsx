"use client";

import { memo } from "react";
import Text from "@/refresh-components/texts/Text";

interface EnabledCountProps {
  name?: string;
  enabledCount: number;
  totalCount: number;
}

const EnabledCount = memo(
  ({ name, enabledCount, totalCount }: EnabledCountProps) => {
    return (
      <Text as="p" text03 mainUiBody>
        <Text mainUiBody className="text-action-link-05" as="span">
          {enabledCount}
        </Text>
        {` of ${totalCount} ${name ?? ""}${
          name && totalCount !== 1 ? "s" : ""
        }`}
      </Text>
    );
  }
);
EnabledCount.displayName = "EnabledCount";

export default EnabledCount;
