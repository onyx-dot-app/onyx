"use client";
import i18n from "@/i18n/init";
import k from "./../../../../../i18n/keys";

import { Label, SubLabel } from "@/components/admin/connectors/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import Text from "@/components/ui/text";
import { useContext, useState } from "react";

export function CustomAnalyticsUpdateForm() {
  const settings = useContext(SettingsContext);
  const customAnalyticsScript = settings?.customAnalyticsScript;

  const [newCustomAnalyticsScript, setNewCustomAnalyticsScript] =
    useState<string>(customAnalyticsScript || "");
  const [secretKey, setSecretKey] = useState<string>("");

  const { popup, setPopup } = usePopup();

  if (!settings) {
    return (
      <Callout type="danger" title={i18n.t(k.FAILED_TO_GET_SETTINGS)}></Callout>
    );
  }

  return (
    <div>
      {popup}
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
            setPopup({
              type: "success",
              message: i18n.t(k.CUSTOM_ANALYTICS_SCRIPT_UPDATE),
            });
          } else {
            const errorMsg = (await response.json()).detail;
            setPopup({
              type: "error",
              message: `${i18n.t(
                k.FAILED_TO_UPDATE_CUSTOM_ANALYT
              )}${errorMsg}${i18n.t(k._17)}`,
            });
          }
          setSecretKey("");
        }}
      >
        <div className="mb-4">
          <Label>{i18n.t(k.SCRIPT)}</Label>
          <Text className="mb-3">
            {i18n.t(k.SPECIFY_THE_JAVASCRIPT_THAT_SH)}
          </Text>
          <Text className="mb-2">
            {i18n.t(k.DO_NOT_INCLUDE_THE)}{" "}
            <span className="font-mono">{i18n.t(k.SCRIPT_SCRIPT)}</span>{" "}
            {i18n.t(k.TAGS_IF_YOU_UPLOAD_A_SCRIPT_B)}
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

        <Label>{i18n.t(k.SECRET_KEY)}</Label>
        <SubLabel>
          <>
            {i18n.t(k.FOR_SECURITY_REASONS_YOU_MUST)}{" "}
            <i>{i18n.t(k.CUSTOM_ANALYTICS_SECRET_KEY)}</i>{" "}
            {i18n.t(k.ENVIRONMENT_VARIABLE_SET_WHEN)}
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
          {i18n.t(k.UPDATE)}
        </Button>
      </form>
    </div>
  );
}
