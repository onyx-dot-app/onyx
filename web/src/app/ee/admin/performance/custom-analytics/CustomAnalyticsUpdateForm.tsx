"use client";

import { useTranslations } from "next-intl";
import { Label, SubLabel } from "@/components/Field";
import { toast } from "@opal/layouts";
import { useCustomAnalyticsScript } from "@/lib/analytics/hooks";
import { Button, InputTextArea, Text } from "@opal/components";
import { markdown } from "@opal/utils";
import { useState } from "react";
import { Spacer } from "@opal/components";

export default function CustomAnalyticsUpdateForm() {
  const t = useTranslations("admin.customAnalytics");
  const customAnalyticsScript = useCustomAnalyticsScript();

  const [newCustomAnalyticsScript, setNewCustomAnalyticsScript] =
    useState<string>(customAnalyticsScript || "");
  const [secretKey, setSecretKey] = useState<string>("");

  return (
    <div>
      <form
        onSubmit={async (e) => {
          e.preventDefault();

          const response = await fetch(
            "/api/admin/enterprise-settings/custom-analytics-script",
            {
              method: "PUT",
              headers: {
                "Content-Type": "application/json",
              },
              body: JSON.stringify({
                script: newCustomAnalyticsScript.trim(),
                secret_key: secretKey,
              }),
            }
          );
          if (response.ok) {
            toast.success(t("updateSuccess.message"));
          } else {
            const errorMsg = (await response.json()).detail;
            toast.error(t("updateFailed.message", { error: errorMsg }));
          }
          setSecretKey("");
        }}
      >
        <div className="mb-4">
          <Label>{t("script.label")}</Label>
          <Text as="p">{t("script.description")}</Text>
          <Spacer rem={0.75} />
          <Text as="p">{markdown(t("script.instructions"))}</Text>
          <Spacer rem={0.5} />
          <InputTextArea
            value={newCustomAnalyticsScript}
            onChange={(event) =>
              setNewCustomAnalyticsScript(event.target.value)
            }
          />
        </div>

        <Label>{t("secretKey.label")}</Label>
        <SubLabel>
          <>
            {t.rich("secretKey.description", {
              i: (chunks) => <i>{chunks}</i>,
            })}
          </>
        </SubLabel>
        <input
          className={`
            border
            border-border
            rounded
            w-full
            py-2
            px-3
            mt-1`}
          type="password"
          value={secretKey}
          onChange={(e) => setSecretKey(e.target.value)}
        />
        <Spacer rem={1} />
        <Button type="submit">{t("updateButton.label")}</Button>
      </form>
    </div>
  );
}
