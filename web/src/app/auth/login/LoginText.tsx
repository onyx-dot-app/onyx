"use client";

import React from "react";
import { useSettings } from "@/lib/settings/hooks";
import Text from "@/refresh-components/texts/Text";

export default function LoginText() {
  const { appName } = useSettings();
  return (
    <div className="w-full flex flex-col ">
      <Text as="p" headingH2 text05>
        Welcome to BEL AI
      </Text>
    </div>
  );
}
