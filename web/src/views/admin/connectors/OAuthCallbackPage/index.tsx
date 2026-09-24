"use client";

import { useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { AdminPageTitle } from "@/components/admin/Title";
import { getSourceMetadata, isValidSource } from "@/lib/sources";
import { ValidSources } from "@/lib/types";
import CardSection from "@/components/admin/CardSection";
import { handleOAuthAuthorizationResponse } from "@/lib/oauth_utils";
import { SvgKey } from "@opal/icons";
import { useTranslations } from "next-intl";

export default function OAuthCallbackPage() {
  const t = useTranslations("admin.connectorsList");
  const searchParams = useSearchParams();

  const [statusMessage, setStatusMessage] = useState(
    t("oauth.processing.title")
  );
  const [statusDetails, setStatusDetails] = useState(
    t("oauth.processing.description")
  );
  const [redirectUrl, setRedirectUrl] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);
  const [pageTitle, setPageTitle] = useState(t("oauthCallback.page.title"));

  // Extract query parameters
  const code = searchParams?.get("code");
  const state = searchParams?.get("state");

  const pathname = usePathname();
  const connector = pathname?.split("/")[3];

  useEffect(() => {
    const onFirstLoad = async () => {
      // Examples
      // connector (url segment)= "google-drive"
      // sourceType (for looking up metadata) = "google_drive"

      if (!code || !state) {
        setStatusMessage(t("oauthCallback.malformed.title"));
        setStatusDetails(
          !code
            ? t("oauthCallback.malformed.missingCode")
            : t("oauthCallback.malformed.missingState")
        );
        setIsError(true);
        return;
      }

      if (!connector) {
        setStatusMessage(
          t("oauth.invalidSource.title", { source: String(connector) })
        );
        setStatusDetails(
          t("oauth.invalidSource.description", {
            source: String(connector),
          })
        );
        setIsError(true);
        return;
      }

      const sourceType = connector.replaceAll("-", "_");
      if (!isValidSource(sourceType)) {
        setStatusMessage(
          t("oauth.invalidSource.title", { source: sourceType })
        );
        setStatusDetails(
          t("oauth.invalidSource.description", { source: sourceType })
        );
        setIsError(true);
        return;
      }

      const sourceMetadata = getSourceMetadata(sourceType as ValidSources);
      setPageTitle(
        t("oauthCallback.authorize.title", {
          source: sourceMetadata.displayName,
        })
      );

      setStatusMessage(t("oauth.processing.title"));
      setStatusDetails(t("oauthCallback.authorizing.description"));
      setIsError(false); // Ensure no error state during loading

      try {
        const response = await handleOAuthAuthorizationResponse(
          connector,
          code,
          state
        );

        if (!response) {
          throw new Error("Empty response from OAuth server.");
        }

        setStatusMessage(t("oauthCallback.success.title"));

        // set the continuation link
        if (response.finalize_url) {
          setRedirectUrl(response.finalize_url);
          setStatusDetails(
            t("oauthCallback.success.additionalSteps.description", {
              source: sourceMetadata.displayName,
            })
          );
        } else {
          setRedirectUrl(response.redirect_on_success);
          setStatusDetails(
            t("oauthCallback.success.description", {
              source: sourceMetadata.displayName,
            })
          );
        }
        setIsError(false);
      } catch (error) {
        console.error("OAuth error:", error);
        setStatusMessage(t("oauth.error.title"));
        setStatusDetails(t("oauthCallback.error.description"));
        setIsError(true);
      }
    };

    onFirstLoad();
  }, [code, state, connector, t]);

  return (
    <div className="mx-auto h-screen flex flex-col">
      <AdminPageTitle title={pageTitle} icon={SvgKey} />

      <div className="flex-1 flex flex-col items-center justify-center">
        <CardSection className="max-w-md w-[500px] h-[250px] p-8">
          <h1 className="text-2xl font-bold mb-4">{statusMessage}</h1>
          <p className="text-text-500">{statusDetails}</p>
          {redirectUrl && !isError && (
            <div className="mt-4">
              <p className="text-sm">
                {t.rich("oauthCallback.continue.message", {
                  link: (chunks) => (
                    <a href={redirectUrl} className="text-blue-500 underline">
                      {chunks}
                    </a>
                  ),
                })}
              </p>
            </div>
          )}
        </CardSection>
      </div>
    </div>
  );
}
