// Each cloud workspace has its own IdP, so this button cannot redirect
// anywhere until an address names one. Google and password sign-in can.

"use client";

import { useState } from "react";
import { Formik } from "formik";
import * as Yup from "yup";
import { Button } from "@opal/components";
import {
  AuthLayouts,
  InputErrorText,
  InputVertical,
  Section,
} from "@opal/layouts";
import { SvgUserKey } from "@opal/icons";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import ProviderSignInButton from "@/app/auth/login/ProviderSignInButton";
import type { SSOProviderOption } from "@/lib/auth/types";
import { discoverSSOProviders } from "@/lib/sso/svc";
import { useTranslations } from "next-intl";

interface LookupValues {
  email: string;
}

interface CloudSSOSignInProps {
  nextUrl: string | null;
}

export default function CloudSSOSignIn({ nextUrl }: CloudSSOSignInProps) {
  const t = useTranslations("auth");
  const [expanded, setExpanded] = useState(false);
  const [providers, setProviders] = useState<SSOProviderOption[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Deliberately the same copy for "no such workspace", "several
  // workspaces" and "workspace without SSO". The endpoint does not
  // distinguish them either.
  const noProvidersMessage = t("login.noSsoProviders.error");

  const lookupSchema = Yup.object({
    email: Yup.string()
      .email(t("login.ssoEmailInvalid.error"))
      .required(t("login.ssoEmailRequired.error")),
  });

  async function handleLookup(values: LookupValues) {
    setError(null);
    try {
      const found = await discoverSSOProviders(values.email.toLowerCase());
      if (found.length === 0) {
        setError(noProvidersMessage);
        return;
      }
      setProviders(found);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }

  if (!expanded) {
    return (
      <Button
        prominence="secondary"
        width="full"
        icon={SvgUserKey}
        onClick={() => setExpanded(true)}
      >
        {t("login.ssoSignInButton.label")}
      </Button>
    );
  }

  return (
    <Section flexDirection="column" gap={4}>
      {providers === null ? (
        <Formik
          initialValues={{ email: "" }}
          validationSchema={lookupSchema}
          onSubmit={handleLookup}
        >
          {({ isSubmitting, isValid, dirty }) => (
            <AuthLayouts.FormBody>
              <AuthLayouts.Fields>
                <InputVertical
                  title={t("login.workEmailField.label")}
                  withLabel="email"
                >
                  <InputTypeInField
                    name="email"
                    placeholder="email@yourcompany.com"
                    data-testid="sso-email"
                    autoComplete="username"
                  />
                </InputVertical>
              </AuthLayouts.Fields>
              <AuthLayouts.Submit
                label="continue"
                isSubmitting={isSubmitting}
                isValid={isValid}
                dirty={dirty}
              />
            </AuthLayouts.FormBody>
          )}
        </Formik>
      ) : (
        providers.map((provider) => (
          <ProviderSignInButton
            key={provider.name}
            provider={provider}
            nextUrl={nextUrl}
          />
        ))
      )}
      {error && <InputErrorText>{error}</InputErrorText>}
    </Section>
  );
}
