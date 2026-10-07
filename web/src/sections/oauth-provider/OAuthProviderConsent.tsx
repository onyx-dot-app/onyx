"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, Text } from "@opal/components";
import { SvgPlug } from "@opal/icons";
import { AuthLayouts, Section } from "@opal/layouts";
import { loginPath } from "@/lib/auth/paths";
import { errorHandlingFetcher, FetchError } from "@/lib/fetcher";
import { submitOAuthProviderConsent } from "@/lib/oauth-provider/api";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  OAuthProviderConsentInfo,
  OAuthProviderDecision,
} from "@/lib/oauth-provider/types";

interface OAuthProviderConsentProps {
  requestId: string;
  userId: string;
}

export default function OAuthProviderConsent({
  requestId,
  userId,
}: OAuthProviderConsentProps) {
  const t = useTranslations("mcpOAuth");
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const { data, error, isLoading, mutate } = useSWR<
    OAuthProviderConsentInfo,
    FetchError
  >(
    [SWR_KEYS.oauthProviderConsent(requestId), userId],
    ([url]: [string, string]) =>
      errorHandlingFetcher<OAuthProviderConsentInfo>(url),
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      shouldRetryOnError: false,
    }
  );

  async function decide(decision: OAuthProviderDecision) {
    if (!data || pending || failed) return;
    setPending(true);
    try {
      const destination = await submitOAuthProviderConsent(
        requestId,
        data.csrf_token,
        decision
      );
      window.location.assign(destination);
    } catch {
      setFailed(true);
      setPending(false);
    }
  }

  const signInUrl = loginPath({
    next: `/oauth-provider/authorize?request=${requestId}`,
  });
  let errorText = t("consent.loadFailed");
  if (error?.status === 401) errorText = t("consent.signInRequired");
  else if (error?.status === 402 || error?.status === 403) {
    errorText = t("consent.forbidden");
  } else if (error?.status === 400 || error?.status === 404) {
    errorText = t("consent.unavailable");
  }
  const canRetry =
    error !== undefined && ![400, 401, 402, 403, 404].includes(error.status);

  return (
    <AuthLayouts.Root>
      <AuthLayouts.Card icon={SvgPlug} title={t("consent.title")}>
        {isLoading ? (
          <Text font="main-ui-body" color="text-04" role="status">
            {t("consent.loading")}
          </Text>
        ) : error || !data ? (
          <Section height="fit" alignItems="stretch">
            <Text font="main-ui-body" color="text-04" role="alert">
              {errorText}
            </Text>
            {error?.status === 401 && (
              <Button href={signInUrl}>{t("consent.signIn")}</Button>
            )}
            {canRetry && (
              <Button prominence="secondary" onClick={() => void mutate()}>
                {t("consent.retry")}
              </Button>
            )}
          </Section>
        ) : (
          <Section height="fit" alignItems="stretch" gap={4}>
            <Text
              font="main-content-emphasis"
              color="text-05"
              wordWrap="wrap-anywhere"
            >
              {t("consent.request", { clientName: data.client_name })}
            </Text>
            <Section height="fit" alignItems="start" gap={1}>
              <Text
                font="main-ui-body"
                color="text-04"
                wordWrap="wrap-anywhere"
              >
                {t("consent.account", { email: data.account_email })}
              </Text>
              <Text
                font="main-ui-body"
                color="text-04"
                wordWrap="wrap-anywhere"
              >
                {t("consent.workspace", { workspaceName: data.workspace_name })}
              </Text>
              <Text
                font="secondary-body"
                color="text-03"
                wordWrap="wrap-anywhere"
              >
                {t("consent.appAddress", { origin: data.redirect_origin })}
              </Text>
            </Section>
            <Text font="main-ui-body" color="text-04">
              {t("consent.access")}
            </Text>
            {failed && (
              <Text font="main-ui-body" role="alert" color="status-error-05">
                {t("consent.failed")}
              </Text>
            )}
            <Button
              width="full"
              disabled={pending || failed}
              onClick={() => void decide("allow")}
            >
              {pending ? t("consent.pending") : t("consent.allow")}
            </Button>
            <Button
              width="full"
              prominence="secondary"
              disabled={pending || failed}
              onClick={() => void decide("deny")}
            >
              {t("consent.deny")}
            </Button>
          </Section>
        )}
      </AuthLayouts.Card>
    </AuthLayouts.Root>
  );
}
