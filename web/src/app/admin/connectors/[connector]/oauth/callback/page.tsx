"use client";

import { useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { AdminPageTitle } from "@/components/admin/Title";
import { getSourceMetadata, isValidSource } from "@/lib/sources";
import { ValidSources } from "@/lib/types";
import CardSection from "@/components/admin/CardSection";
import { handleOAuthAuthorizationResponse } from "@/lib/oauth_utils";
import { SvgKey } from "@opal/icons";
export default function OAuthCallbackPage() {
  const searchParams = useSearchParams();
  const t = useTranslations("admin.oauth");

  const [statusMessage, setStatusMessage] = useState(t("processing"));
  const [statusDetails, setStatusDetails] = useState(
    t("pleaseWaitSetup")
  );
  const [redirectUrl, setRedirectUrl] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);
  const [pageTitle, setPageTitle] = useState(
    t("authorizeWithThirdParty")
  );

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
        setStatusMessage(t("improperlyFormedRequest"));
        setStatusDetails(
          !code ? t("missingAuthCode") : t("missingStateParam")
        );
        setIsError(true);
        return;
      }

      if (!connector) {
        setStatusMessage(
          t("connectorNotExist", { sourceType: connector ?? "" })
        );
        setStatusDetails(t("notValidSourceType", { sourceType: connector ?? "" }));
        setIsError(true);
        return;
      }

      const sourceType = connector.replaceAll("-", "_");
      if (!isValidSource(sourceType)) {
        setStatusMessage(
          t("connectorNotExist", { sourceType })
        );
        setStatusDetails(t("notValidSourceType", { sourceType }));
        setIsError(true);
        return;
      }

      const sourceMetadata = getSourceMetadata(sourceType as ValidSources);
      setPageTitle(t("authorizeWith", { provider: sourceMetadata.displayName }));

      setStatusMessage(t("processing"));
      setStatusDetails(t("pleaseWaitAuth"));
      setIsError(false); // Ensure no error state during loading

      try {
        const response = await handleOAuthAuthorizationResponse(
          connector,
          code,
          state
        );

        if (!response) {
          throw new Error(t("emptyResponse"));
        }

        setStatusMessage(t("success"));

        // set the continuation link
        if (response.finalize_url) {
          setRedirectUrl(response.finalize_url);
          setStatusDetails(
            t("authCompletedWithSteps", { provider: sourceMetadata.displayName })
          );
        } else {
          setRedirectUrl(response.redirect_on_success);
          setStatusDetails(
            t("authCompleted", { provider: sourceMetadata.displayName })
          );
        }
        setIsError(false);
      } catch (error) {
        console.error("OAuth error:", error);
        setStatusMessage(t("oopsWrong"));
        setStatusDetails(
          t("oauthError")
        );
        setIsError(true);
      }
    };

    onFirstLoad();
  }, [code, state, connector]);

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
                {"Click "}<a href={redirectUrl} className="text-blue-500 underline">{t("clickHere")}</a>{" to continue."}
              </p>
            </div>
          )}
        </CardSection>
      </div>
    </div>
  );
}
