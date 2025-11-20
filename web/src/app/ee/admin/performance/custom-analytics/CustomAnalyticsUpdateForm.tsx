"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../../i18n/keys";

import { Label, SubLabel } from "@/components/admin/connectors/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import Text from "@/components/ui/text";
import { useContext, useState } from "react";

export function CustomAnalyticsUpdateForm() {
  const { t } = useTranslation();
  const settings = useContext(SettingsContext);
  const customAnalyticsScript = settings?.customAnalyticsScript;

  const [newCustomAnalyticsScript, setNewCustomAnalyticsScript] =
    useState<string>(customAnalyticsScript || "");
  const [secretKey, setSecretKey] = useState<string>("");

  const { popup, setPopup } = usePopup();

  if (!settings) {
    return (
      <Callout type="danger" title={t(k.FAILED_TO_GET_SETTINGS)}></Callout>
    );
  }

  return (
    <div>
      {popup}
      <form
        onSubmit={async (e) => {
          e.preventDefault();

          const response = await fetch(
            "/api/admin/settings/custom-analytics-script",
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
            setPopup({
              type: "success",
              message: t(k.CUSTOM_ANALYTICS_SCRIPT_UPDATE),
            });
          } else {
            const errorMsg = (await response.json()).detail;
            setPopup({
              type: "error",
              message: `${t(k.FAILED_TO_UPDATE_CUSTOM_ANALYT)}${errorMsg}${t(
                k._17
              )}`,
            });
          }
          setSecretKey("");
        }}
      >
        <div className="mb-4">
          <Label>{t(k.SCRIPT)}</Label>
          <Text className="mb-3">{t(k.SPECIFY_THE_JAVASCRIPT_THAT_SH)}</Text>
          <Text className="mb-2">
            {t(k.DO_NOT_INCLUDE_THE)}{" "}
            <span className="font-mono">{t(k.SCRIPT_SCRIPT)}</span>{" "}
            {t(k.TAGS_IF_YOU_UPLOAD_A_SCRIPT_B)}
          </Text>
          <textarea
            className={`
              border 
              border-border 
              rounded 
              w-full 
              py-2 
              px-3 
              mt-1
              h-28`}
            value={newCustomAnalyticsScript}
            onChange={(e) => setNewCustomAnalyticsScript(e.target.value)}
          />
        </div>

        <Label>{t(k.SECRET_KEY)}</Label>
        <SubLabel>
          <>
            {t(k.FOR_SECURITY_REASONS_YOU_MUST)}{" "}
            <i>{t(k.CUSTOM_ANALYTICS_SECRET_KEY)}</i>{" "}
            {t(k.ENVIRONMENT_VARIABLE_SET_WHEN)}
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

        <Button className="mt-4" type="submit">
          {t(k.UPDATE)}
        </Button>
      </form>
    </div>
  );
}
