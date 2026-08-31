"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { Button, Card, OnyxLoader, Text } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import {
  SvgBrokenKey,
  SvgConnected,
  SvgPlugBroken,
  SvgTimeout,
  SvgUnPlugged,
} from "@opal/illustrations";
import type { IconFunctionComponent } from "@opal/types";
import { completeMCPUserOAuth } from "@/lib/tools/svc";
import { useTranslations } from "next-intl";

const AUTO_REDIRECT_DELAY_MS = 2000;
const DEFAULT_REDIRECT_PATH = "/app";

type CallbackTranslate = ReturnType<typeof useTranslations<"actions">>;

interface CallbackError {
  illustration: IconFunctionComponent;
  title: string;
  description: string;
}

type CallbackState =
  | { phase: "processing" }
  | { phase: "success"; serverName: string; redirectPath: string }
  | { phase: "error"; error: CallbackError };

function cancelledError(
  t: CallbackTranslate,
  errorDescription: string | null
): CallbackError {
  return {
    illustration: SvgUnPlugged,
    title: t("mcpOauthCallback.cancelled.title"),
    description:
      errorDescription || t("mcpOauthCallback.cancelled.description"),
  };
}

function invalidLinkError(t: CallbackTranslate): CallbackError {
  return {
    illustration: SvgBrokenKey,
    title: t("mcpOauthCallback.invalidLink.title"),
    description: t("mcpOauthCallback.invalidLink.description"),
  };
}

// Maps the backend's error `detail` strings to actionable guidance. Order
// matters: "No tokens found" must match before the generic "token" and
// "not found" checks.
function classifyCallbackError(
  t: CallbackTranslate,
  detail: string
): CallbackError {
  const lowerDetail = detail.toLowerCase();

  if (lowerDetail.includes("state")) {
    return {
      illustration: SvgBrokenKey,
      title: t("mcpOauthCallback.sessionExpired.title"),
      description: t("mcpOauthCallback.sessionExpired.description"),
    };
  }
  if (lowerDetail.includes("no tokens found")) {
    return {
      illustration: SvgTimeout,
      title: t("mcpOauthCallback.timedOut.title"),
      description: t("mcpOauthCallback.timedOut.description"),
    };
  }
  if (
    lowerDetail.includes("token exchange") ||
    lowerDetail.includes("access_token")
  ) {
    return {
      illustration: SvgPlugBroken,
      title: t("mcpOauthCallback.tokenExchangeFailed.title"),
      description: t("mcpOauthCallback.tokenExchangeFailed.description"),
    };
  }
  if (
    lowerDetail.includes("not found") ||
    lowerDetail.includes("not configured")
  ) {
    return {
      illustration: SvgPlugBroken,
      title: t("mcpOauthCallback.serverNotFound.title"),
      description: t("mcpOauthCallback.serverNotFound.description"),
    };
  }
  return {
    illustration: SvgPlugBroken,
    title: t("mcpOauthCallback.genericError.title"),
    description: detail,
  };
}

// Respect the backend-provided redirect path (from state.return_path) while
// preventing open redirects (e.g. "//evil.com" or absolute URLs).
function buildRedirectPath(rawPath: string): string {
  const sanitizedPath =
    rawPath.startsWith("http://") || rawPath.startsWith("https://")
      ? DEFAULT_REDIRECT_PATH
      : "/" + rawPath.replace(/^\/+/, "");
  const redirectUrl = new URL(sanitizedPath, window.location.origin);
  redirectUrl.searchParams.set("message", "oauth_connected");
  return redirectUrl.pathname + redirectUrl.search;
}

export default function MCPOAuthCallbackPage() {
  const t = useTranslations("actions");
  const router = useRouter();
  const searchParams = useSearchParams();

  const [state, setState] = useState<CallbackState>({ phase: "processing" });

  // State + auth code are single-use; block duplicate POSTs (StrictMode
  // double-invoke or re-renders) that race the first request and 400.
  const hasProcessedRef = useRef(false);

  useEffect(() => {
    if (state.phase !== "success") return;
    const timer = setTimeout(
      () => router.push(state.redirectPath as Route),
      AUTO_REDIRECT_DELAY_MS
    );
    return () => clearTimeout(timer);
  }, [state, router]);

  useEffect(() => {
    if (hasProcessedRef.current) return;
    hasProcessedRef.current = true;

    const code = searchParams?.get("code");
    const stateParam = searchParams?.get("state");
    const providerError = searchParams?.get("error");
    const errorDescription = searchParams?.get("error_description");

    // The provider redirected back with an error (e.g. the user cancelled)
    if (providerError) {
      setState({ phase: "error", error: cancelledError(t, errorDescription) });
      return;
    }

    if (!code || !stateParam) {
      setState({ phase: "error", error: invalidLinkError(t) });
      return;
    }

    const handleOAuthCallback = async () => {
      try {
        const response = await completeMCPUserOAuth(code, stateParam);
        setState({
          phase: "success",
          serverName: response.server_name,
          redirectPath: buildRedirectPath(
            response.redirect_url || DEFAULT_REDIRECT_PATH
          ),
        });
      } catch (error) {
        setState({
          phase: "error",
          error: classifyCallbackError(
            t,
            error instanceof Error
              ? error.message
              : t("mcpOauthCallback.genericError.fallbackDetail")
          ),
        });
      }
    };

    handleOAuthCallback();
    // Run once; the single-use callback must not re-fire (see hasProcessedRef).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <Card padding={6} rounding={4} background="light" border="solid">
          <div className="flex flex-col items-stretch gap-4">
            {state.phase === "processing" && (
              <div className="flex flex-col items-center gap-3 p-5 text-center">
                {/* Match the illustration footprint so success/error don't shift layout */}
                <div className="flex h-30 w-30 items-center justify-center">
                  <OnyxLoader />
                </div>
                <div className="flex flex-col items-center text-center">
                  <Text font="main-content-emphasis" color="text-04" as="p">
                    {t("mcpOauthCallback.processing.title")}
                  </Text>
                  <Text font="secondary-body" color="text-03" as="p">
                    {t("mcpOauthCallback.processing.description")}
                  </Text>
                </div>
              </div>
            )}

            {state.phase === "success" && (
              <>
                <IllustrationContent
                  illustration={SvgConnected}
                  title={t("mcpOauthCallback.success.title", {
                    serverName: state.serverName,
                  })}
                  description={t("mcpOauthCallback.success.description")}
                />
                <Button
                  width="full"
                  onClick={() => router.push(state.redirectPath as Route)}
                >
                  {t("mcpOauthCallback.continueButton.label")}
                </Button>
                <div className="flex justify-center">
                  <Text font="secondary-body" color="text-03" as="p">
                    {t("mcpOauthCallback.autoRedirect.text")}
                  </Text>
                </div>
              </>
            )}

            {state.phase === "error" && (
              <>
                <IllustrationContent
                  illustration={state.error.illustration}
                  title={state.error.title}
                  description={state.error.description}
                />
                <Button
                  width="full"
                  onClick={() => router.push(DEFAULT_REDIRECT_PATH as Route)}
                >
                  {t("mcpOauthCallback.backToChatButton.label")}
                </Button>
              </>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
