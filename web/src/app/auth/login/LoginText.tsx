"use client";

import React from "react";
import { useAppName } from "@/lib/settings/hooks";
import Text from "@/refresh-components/texts/Text";

export default function LoginText() {
  const appName = useAppName();
  return (
    <div className="w-full flex flex-col ">
      <Text as="p" headingH2 text05>
        Welcome to {appName}
      </Text>
      <Text as="p" text03 mainUiMuted>
        Your open source AI platform for work
      </Text>
    </div>
  );
}
