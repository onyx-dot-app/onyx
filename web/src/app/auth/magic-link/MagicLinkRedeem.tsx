"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Formik } from "formik";
import * as Yup from "yup";
import { Button, Text } from "@opal/components";
import { AuthLayouts, InputVertical, Section } from "@opal/layouts";
import { useNavigation, useSearchParams } from "@opal/navigation";
import { useTranslations } from "next-intl";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { authErrorPath, loginPath } from "@/lib/auth/paths";
import { redeemMagicLink } from "@/lib/auth/svc";
import { MagicLinkRefusal } from "@/lib/auth/types";
import { validateInternalRedirect } from "@/lib/auth/utils";
import { FetchError } from "@/lib/fetcher";

const CONFIRM_EMAIL_FIELD = "magicLinkConfirmEmail";

interface ConfirmValues {
  [CONFIRM_EMAIL_FIELD]: string;
}

/** Redeems the emailed token once, then signs in, asks for the address when
 * the link was opened in another browser, asks the playground's join-or-new
 * question, or shows why the link was refused. */
export default function MagicLinkRedeem() {
  const t = useTranslations("auth");
  const tPlaceholders = useTranslations("common.placeholders");
  const navigation = useNavigation();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  // The token works once, and the effect can run again: dev StrictMode, or
  // a re-render with new dependencies.
  const started = useRef(false);
  const [confirmingEmail, setConfirmingEmail] = useState(false);
  const [teamChoiceToken, setTeamChoiceToken] = useState<string | null>(null);
  const [joinChosen, setJoinChosen] = useState(false);
  const [startingTeam, setStartingTeam] = useState(false);

  const confirmSchema = Yup.object({
    [CONFIRM_EMAIL_FIELD]: Yup.string()
      .trim()
      .email(t("login.ssoEmailInvalid.error"))
      .required(t("login.ssoEmailRequired.error")),
  });

  const redeem = useCallback(
    async (value: string, email?: string) => {
      try {
        const result = await redeemMagicLink(value, email);
        if (result.state === "confirm_email") {
          setConfirmingEmail(true);
          return;
        }
        if (result.state === "team_choice") {
          setConfirmingEmail(false);
          setTeamChoiceToken(result.team_choice_token);
          setStartingTeam(false);
          return;
        }
        // A full load: the app starts again with the new session.
        navigation.load(validateInternalRedirect(result.next_url) ?? "/app", {
          replace: true,
        });
      } catch (exc) {
        // A refusal carries its code for the error page; anything else gets
        // the page's general message.
        navigation.go(
          authErrorPath(exc instanceof FetchError ? exc.message : null),
          { replace: true }
        );
      }
    },
    [navigation]
  );

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    if (!token) {
      navigation.go(authErrorPath(MagicLinkRefusal.INVALID), {
        replace: true,
      });
      return;
    }
    void redeem(token);
  }, [token, redeem, navigation]);

  if (confirmingEmail && token) {
    return (
      <AuthFlowContainer>
        <Section flexDirection="column" gap={4}>
          <Text as="p" font="heading-headline" color="text-05">
            {t("magicLink.confirmEmail.title")}
          </Text>
          <Text as="p" font="main-content-body" color="text-03">
            {t("magicLink.confirmEmail.description")}
          </Text>
          <Formik
            initialValues={{ [CONFIRM_EMAIL_FIELD]: "" }}
            validationSchema={confirmSchema}
            onSubmit={async (values: ConfirmValues) => {
              await redeem(token, values[CONFIRM_EMAIL_FIELD].trim());
            }}
          >
            {({ isSubmitting, isValid, dirty }) => (
              <AuthLayouts.FormBody>
                <AuthLayouts.Fields>
                  <InputVertical
                    title={t("login.workEmailField.label")}
                    withLabel={CONFIRM_EMAIL_FIELD}
                  >
                    <InputTypeInField
                      name={CONFIRM_EMAIL_FIELD}
                      placeholder={tPlaceholders("email")}
                      data-testid="magic-link-confirm-email"
                      autoComplete="email"
                    />
                  </InputVertical>
                </AuthLayouts.Fields>
                <AuthLayouts.Submit
                  isSubmitting={isSubmitting}
                  isValid={isValid}
                  dirty={dirty}
                >
                  {t("login.continueButton.label")}
                </AuthLayouts.Submit>
              </AuthLayouts.FormBody>
            )}
          </Formik>
        </Section>
      </AuthFlowContainer>
    );
  }

  if (teamChoiceToken === null) {
    return (
      <AuthFlowContainer>
        <Text as="p" font="main-content-body" color="text-03">
          {t("magicLink.redeeming.text")}
        </Text>
      </AuthFlowContainer>
    );
  }

  return (
    <AuthFlowContainer>
      <Section flexDirection="column" gap={4}>
        <Text as="p" font="heading-headline" color="text-05">
          {t("error.playgroundHeading.title")}
        </Text>
        <Text as="p" font="main-content-body" color="text-05">
          {joinChosen
            ? t("error.code.playgroundAskAdmin")
            : t("error.code.playgroundActiveTenant")}
        </Text>
        {joinChosen ? (
          <Button
            prominence="secondary"
            width="full"
            {...navigation.linkTo(loginPath({ autoRedirectToSso: false }))}
          >
            {t("error.returnToLoginButton.label")}
          </Button>
        ) : (
          <>
            <Button
              width="full"
              disabled={startingTeam}
              onClick={() => {
                // The fresh token carries "start a new team": no second email.
                setStartingTeam(true);
                void redeem(teamChoiceToken);
              }}
            >
              {t("error.startNewTeamButton.label")}
            </Button>
            <Button
              prominence="secondary"
              width="full"
              disabled={startingTeam}
              onClick={() => setJoinChosen(true)}
            >
              {t("error.joinTeamButton.label")}
            </Button>
          </>
        )}
      </Section>
    </AuthFlowContainer>
  );
}
