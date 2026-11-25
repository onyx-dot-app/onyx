"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { useNavigation, useSearchParams } from "@opal/navigation";
import { useTranslations } from "next-intl";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import { authErrorPath, loginPath } from "@/lib/auth/paths";
import { redeemMagicLink } from "@/lib/auth/svc";
import { MagicLinkRefusal } from "@/lib/auth/types";
import { validateInternalRedirect } from "@/lib/auth/utils";
import { FetchError } from "@/lib/fetcher";

/** Redeems the emailed token once, then signs in, asks the playground's
 * join-or-new question, or shows why the link was refused. */
export default function MagicLinkRedeem() {
  const t = useTranslations("auth");
  const navigation = useNavigation();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  // The token works once, and the effect can run again: dev StrictMode, or
  // a re-render with new dependencies.
  const started = useRef(false);
  const [teamChoiceToken, setTeamChoiceToken] = useState<string | null>(null);
  const [joinChosen, setJoinChosen] = useState(false);
  const [startingTeam, setStartingTeam] = useState(false);

  const redeem = useCallback(
    async (value: string) => {
      try {
        const result = await redeemMagicLink(value);
        if (result.state === "team_choice") {
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

  if (teamChoiceToken === null) {
    return (
      <AuthFlowContainer>
        <Text as="p" color="text-03">
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
        <Text as="p" color="text-05">
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
