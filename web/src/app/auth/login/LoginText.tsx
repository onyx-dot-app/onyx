"use client";

import React from "react";
import { useContext } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";

export const LoginText = () => {
  const settings = useContext(SettingsContext);

  if (!settings) {
    throw new Error("SettingsContext is not available");
  }

  return (
    <>Log In to {settings?.enterpriseSettings?.application_name || "Danswer"}</>
  );
};
