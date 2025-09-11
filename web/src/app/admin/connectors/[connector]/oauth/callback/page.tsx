"use client";
import i18n from "@/i18n/init";
import k from "./../../../../../../i18n/keys";

import { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { AdminPageTitle } from "@/components/admin/Title";
import { Button } from "@/components/ui/button";
import Title from "@/components/ui/title";
import { KeyIcon } from "@/components/icons/icons";
import { getSourceMetadata, isValidSource } from "@/lib/sources";
import { ValidSources } from "@/lib/types";
import CardSection from "@/components/admin/CardSection";
import { handleOAuthAuthorizationResponse } from "@/lib/oauth_utils";

export default function OAuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [statusMessage, setStatusMessage] = useState(i18n.t(k.PROCESSING));
  const [statusDetails, setStatusDetails] = useState(
    i18n.t(k.PLEASE_WAIT_SETUP)
  );
  const [redirectUrl, setRedirectUrl] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);
  const [pageTitle, setPageTitle] = useState(
    "Authorize with Third-Party service"
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
        setStatusMessage(i18n.t(k.MALFORMED_OAUTH_REQUEST));
        setStatusDetails(
          !code ? i18n.t(k.MISSING_AUTH_CODE) : i18n.t(k.MISSING_STATE_PARAM)
        );
        setIsError(true);
        return;
      }

      if (!connector) {
        setStatusMessage(
          i18n.t(k.CONNECTOR_SOURCE_TYPE_NOT_EXIST, { connector })
        );
        setStatusDetails(i18n.t(k.INVALID_SOURCE_TYPE, { connector }));
        setIsError(true);
        return;
      }

      const sourceType = connector.replaceAll("-", "_");
      if (!isValidSource(sourceType)) {
        setStatusMessage(
          i18n.t(k.CONNECTOR_SOURCE_TYPE_NOT_EXIST, { connector: sourceType })
        );
        setStatusDetails(
          i18n.t(k.INVALID_SOURCE_TYPE, { connector: sourceType })
        );
        setIsError(true);
        return;
      }

      const sourceMetadata = getSourceMetadata(sourceType as ValidSources);
      setPageTitle(
        i18n.t(k.AUTHORIZE_WITH_SERVICE, {
          service: sourceMetadata.displayName,
        })
      );

      setStatusMessage(i18n.t(k.PROCESSING));
      setStatusDetails(i18n.t(k.PLEASE_WAIT_AUTHORIZATION));
      setIsError(false); // Ensure no error state during loading

      try {
        const response = await handleOAuthAuthorizationResponse(
          connector,
          code,
          state
        );

        if (!response) {
          throw new Error(i18n.t(k.EMPTY_OAUTH_RESPONSE));
        }

        setStatusMessage(i18n.t(k.SUCCESS_EXCLAMATION));
        if (response.finalize_url) {
          setRedirectUrl(response.finalize_url);
          setStatusDetails(
            i18n.t(k.AUTHORIZATION_COMPLETE_ADDITIONAL_STEPS, {
              service: sourceMetadata.displayName,
            })
          );
        } else {
          setRedirectUrl(response.redirect_on_success);
          setStatusDetails(
            i18n.t(k.AUTHORIZATION_COMPLETE, {
              service: sourceMetadata.displayName,
            })
          );
        }
        setIsError(false);
      } catch (error) {
        console.error("OAuth error:", error);
        setStatusMessage(i18n.t(k.OOPS_SOMETHING_WRONG));
        setStatusDetails(i18n.t(k.OAUTH_ERROR_TRY_AGAIN));
        setIsError(true);
      }
    };

    onFirstLoad();
  }, [code, state, connector]);

  return (
    <div className="mx-auto h-screen flex flex-col">
      <AdminPageTitle title={pageTitle} icon={<KeyIcon size={32} />} />

      <div className="flex-1 flex flex-col items-center justify-center">
        <CardSection className="max-w-md w-[500px] h-[250px] p-8">
          <h1 className="text-2xl font-bold mb-4">{statusMessage}</h1>
          <p className="text-text-500">{statusDetails}</p>
          {redirectUrl && !isError && (
            <div className="mt-4">
              <p className="text-sm">
                {i18n.t(k.CLICK)}{" "}
                <a href={redirectUrl} className="text-blue-500 underline">
                  {i18n.t(k.HERE)}
                </a>{" "}
                {i18n.t(k.TO_CONTINUE)}
              </p>
            </div>
          )}
        </CardSection>
      </div>
    </div>
  );
}
