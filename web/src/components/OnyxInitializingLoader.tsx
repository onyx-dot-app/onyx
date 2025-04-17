import i18n from "@/i18n/init";
import k from "./../i18n/keys";
import { Logo } from "./logo/Logo";
import { useContext } from "react";
import { SettingsContext } from "./settings/SettingsProvider";

export function OnyxInitializingLoader() {
  const settings = useContext(SettingsContext);

  return (
    <div className="mx-auto my-auto animate-pulse">
      <Logo height={96} width={96} className="mx-auto mb-3" />
      <p className="text-lg text-text font-semibold">
        {i18n.t(k.INITIALIZING)}{" "}
        {settings?.enterpriseSettings?.application_name ?? "SmartSearch"}
      </p>
    </div>
  );
}
