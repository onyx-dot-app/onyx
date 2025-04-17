"use client";
import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";

import React, { useContext } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";

export const LoginText = () => {
  const settings = useContext(SettingsContext);
  return (
    <>
      {i18n.t(k.LOG_IN_TO)}{" "}
      {(settings && settings?.enterpriseSettings?.application_name) || "Onyx"}
    </>
  );
};
