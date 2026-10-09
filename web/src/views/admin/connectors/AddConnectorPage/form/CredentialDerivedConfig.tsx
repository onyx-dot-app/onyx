"use client";

import { useEffect } from "react";
import { useFormikContext } from "formik";
import type { ConnectionConfiguration } from "@/lib/connectors/types";
import type { Credential } from "@/lib/credentials/types";

export interface CredentialDerivedConfigProps {
  configuration: ConnectionConfiguration;
  credential: Credential<unknown> | null;
}

/**
 * Sets the config values that follow from the picked credential
 * (`configFromCredential`) whenever the credential changes. Renders nothing.
 */
export function CredentialDerivedConfig({
  configuration,
  credential,
}: CredentialDerivedConfigProps) {
  const { setFieldValue } = useFormikContext<Record<string, unknown>>();
  const derived = configuration.configFromCredential?.(credential) ?? {};
  // `derivedKey` holds everything the effect writes, so equal values are not
  // written again.
  const derivedKey = JSON.stringify(derived);
  useEffect(() => {
    for (const [name, value] of Object.entries(derived)) {
      void setFieldValue(name, value);
    }
  }, [derivedKey]);

  return null;
}
