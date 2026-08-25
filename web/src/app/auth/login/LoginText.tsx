"use client";

import React from "react";
import { useSettings } from "@/lib/settings/hooks";
import { welcomeCardCopy } from "@/lib/auth/copies";
import Text from "@/refresh-components/texts/Text";

export default function LoginText() {
  const { appName, enterprise } = useSettings();
  const { title, description } = welcomeCardCopy(
    appName,
    enterprise?.custom_login_subtitle
  );
  return (
    <div className="w-full flex flex-col ">
      <Text as="p" headingH2 text05>
        {title}
      </Text>
      <Text as="p" text03 mainUiMuted>
        {description}
      </Text>
    </div>
  );
}
