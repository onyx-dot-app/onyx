"use client";

import { DEFAULT_APPLICATION_NAME } from "@/lib/constants";
import { useContext } from "react";
import Logo from "@/refresh-components/Logo";
import Text from "@/refresh-components/texts/Text";
import { SettingsContext } from "@/providers/SettingsProvider";

export default function ActivaInitializingLoader() {
  const settings = useContext(SettingsContext);
  const applicationName =
    settings?.enterpriseSettings?.application_name ?? DEFAULT_APPLICATION_NAME;

  return (
    <div className="mx-auto my-auto flex flex-col items-center gap-3 animate-pulse">
      <Logo folded size={96} />
      <Text as="p" text05 className="text-lg font-semibold">
        Initializing {applicationName}
      </Text>
    </div>
  );
}
