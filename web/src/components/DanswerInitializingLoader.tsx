import { Bold } from "@tremor/react";
import { Logo } from "./Logo";
import { useContext } from "react";
import { SettingsContext } from "./settings/SettingsProvider";

export function DanswerInitializingLoader() {
  const settings = useContext(SettingsContext);

  return (
    <div className="mx-auto my-auto animate-pulse">
      <Logo height={96} width={96} className="mx-auto mb-3" />
      <Bold>
        Initializing{" "}
        {settings?.enterpriseSettings?.application_name ?? "Danswer"}
      </Bold>
    </div>
  );
}
