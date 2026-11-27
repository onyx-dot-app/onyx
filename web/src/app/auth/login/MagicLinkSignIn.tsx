"use client";

import { useState } from "react";
import { Formik } from "formik";
import * as Yup from "yup";
import { Button, MessageCard } from "@opal/components";
import {
  AuthLayouts,
  InputErrorText,
  InputVertical,
  Section,
} from "@opal/layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { requestMagicLink } from "@/lib/auth/svc";
import { MagicLinkRefusal } from "@/lib/auth/types";
import { FetchError } from "@/lib/fetcher";
import { useTranslations } from "next-intl";

// Its own field name, so its id does not clash with the password or SSO
// form's "email" field on the same page.
const EMAIL_FIELD = "magicLinkEmail";

interface RequestValues {
  [EMAIL_FIELD]: string;
}

interface MagicLinkSignInProps {
  nextUrl: string | null;
  /** Playground: the person chose "start a new team" on /auth/error. */
  startNewTeam?: boolean;
  /** Prefill, such as the address an invitation was sent to. */
  defaultEmail?: string | null;
}

/** "Get a link by email": asks for an address, then says where the link went. */
export default function MagicLinkSignIn({
  nextUrl,
  startNewTeam = false,
  defaultEmail = null,
}: MagicLinkSignInProps) {
  const t = useTranslations("auth");
  const tPlaceholders = useTranslations("common.placeholders");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const requestSchema = Yup.object({
    // Pasted addresses often carry spaces; the request trims them too.
    [EMAIL_FIELD]: Yup.string()
      .trim()
      .email(t("login.ssoEmailInvalid.error"))
      .required(t("login.ssoEmailRequired.error")),
  });

  /** `refusal` is null when the request never got an answer. */
  function refusalMessage(refusal: FetchError | null): string {
    if (refusal === null) return t("magicLink.sendFailed.error");
    if (refusal.status === 429) return t("magicLink.resendWait.error");
    if (refusal.message === MagicLinkRefusal.PLAYGROUND_FREE_MAIL) {
      return t("error.code.playgroundFreeMail");
    }
    if (refusal.message === MagicLinkRefusal.USE_SSO) {
      return t("magicLink.useSso.error");
    }
    // A 4xx detail is a sentence for the person, such as a refused domain.
    return refusal.status < 500
      ? refusal.message
      : t("magicLink.sendFailed.error");
  }

  async function handleRequest(values: RequestValues) {
    setError(null);
    const email = values[EMAIL_FIELD].trim().toLowerCase();
    try {
      await requestMagicLink(email, { nextUrl, startNewTeam });
      setSentTo(email);
    } catch (exc) {
      setError(refusalMessage(exc instanceof FetchError ? exc : null));
    }
  }

  return (
    <Section flexDirection="column" gap={4}>
      {/* Mounted before the request, so screen readers announce what is
          put into it when the link goes out. Visually hidden and out of the
          layout, so it adds no gap while empty. */}
      <div role="status" aria-live="polite" className="sr-only">
        {sentTo !== null && t("magicLink.sent.description", { email: sentTo })}
      </div>
      {sentTo !== null && (
        <MessageCard
          variant="success"
          title={t("magicLink.sent.title")}
          description={t("magicLink.sent.description", { email: sentTo })}
        />
      )}
      {sentTo !== null ? (
        <Button
          prominence="secondary"
          width="full"
          onClick={() => setSentTo(null)}
        >
          {t("magicLink.differentEmailButton.label")}
        </Button>
      ) : (
        <Formik
          initialValues={{ [EMAIL_FIELD]: defaultEmail ?? "" }}
          validationSchema={requestSchema}
          onSubmit={handleRequest}
        >
          {({ isSubmitting, isValid, dirty }) => (
            <AuthLayouts.FormBody>
              <AuthLayouts.Fields>
                <InputVertical
                  title={t("login.workEmailField.label")}
                  withLabel={EMAIL_FIELD}
                >
                  <InputTypeInField
                    name={EMAIL_FIELD}
                    placeholder={tPlaceholders("email")}
                    data-testid="magic-link-email"
                    autoComplete="email"
                  />
                </InputVertical>
              </AuthLayouts.Fields>
              <AuthLayouts.Submit
                isSubmitting={isSubmitting}
                isValid={isValid}
                // A prefilled address can be sent as it is.
                dirty={dirty || Boolean(defaultEmail)}
              >
                {t("magicLink.requestButton.label")}
              </AuthLayouts.Submit>
            </AuthLayouts.FormBody>
          )}
        </Formik>
      )}
      {error && <InputErrorText>{error}</InputErrorText>}
    </Section>
  );
}
