"use client";

import React, { useContext } from "react";
import { DEFAULT_APPLICATION_NAME } from "@/lib/constants";
import AuthPanelIntro from "@/components/auth/AuthPanelIntro";
import { SettingsContext } from "@/providers/SettingsProvider";

export default function LoginText() {
  const settings = useContext(SettingsContext);
  return (
    <AuthPanelIntro
      eyebrow="Cuenta"
      description="Accede a tu espacio de trabajo con contexto, permisos y trazabilidad."
    >
      Inicia sesion en{" "}
      <span className="text-[var(--landing-accent)]">
        {(settings && settings?.enterpriseSettings?.application_name) ||
          DEFAULT_APPLICATION_NAME}
      </span>
    </AuthPanelIntro>
  );
}
