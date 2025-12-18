"use client";

import React, { memo } from "react";
import Text from "@/refresh-components/texts/Text";

interface ToolsEnabledCountProps {
  enabledCount: number;
  totalCount: number;
  countClassName?: string;
}

const ToolsEnabledCountInner: React.FC<ToolsEnabledCountProps> = ({
  enabledCount,
  totalCount,
  countClassName = "text-action-link-05",
}) => {
  return (
    <>
      <Text mainUiBody className={countClassName}>
        {enabledCount}
      </Text>
      <Text text03 mainUiBody>
        {`of ${totalCount} tool${totalCount !== 1 ? "s" : ""} enabled`}
      </Text>
    </>
  );
};

const ToolsEnabledCount = memo(ToolsEnabledCountInner);
ToolsEnabledCount.displayName = "ToolsEnabledCount";

export default ToolsEnabledCount;
