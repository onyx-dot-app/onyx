"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { AdminPageTitle } from "@/components/admin/Title";
import { KeyIcon } from "@/components/icons/icons";
import { getSourceMetadata, isValidSource } from "@/lib/sources";
import { ValidSources } from "@/lib/types";
import CardSection from "@/components/admin/CardSection";
import { handleOAuthAuthorizationResponse } from "@/lib/oauth_utils";

export default function OAuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [statusMessage, setStatusMessage] = useState("Processing...");
  const [statusDetails, setStatusDetails] = useState(
    "Please wait while we complete the setup."
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
        setStatusMessage("Improperly formed OAuth authorization request.");
        setStatusDetails(
          !code ? "Missing authorization code." : "Missing state parameter."
        );
        setIsError(true);
        return;
      }

      if (!connector) {
        setStatusMessage(
          `The specified connector source type ${connector} does not exist.`
        );
        setStatusDetails(`${connector} is not a valid source type.`);
        setIsError(true);
        return;
      }

      const sourceType = connector.replaceAll("-", "_");
      if (!isValidSource(sourceType)) {
        setStatusMessage(
          `The specified connector source type ${sourceType} does not exist.`
        );
        setStatusDetails(`${sourceType} is not a valid source type.`);
        setIsError(true);
        return;
      }

      const sourceMetadata = getSourceMetadata(sourceType as ValidSources);
      setPageTitle(`Authorize with ${sourceMetadata.displayName}`);

      setStatusMessage("Processing...");
      setStatusDetails("Please wait while we complete authorization.");
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

        setStatusMessage("Success!");

        // set the continuation link
        if (response.finalize_url) {
          setRedirectUrl(response.finalize_url);
          setStatusDetails(
            `Your authorization with ${sourceMetadata.displayName} completed successfully. Additional steps are required to complete credential setup.`
          );
        } else {
          setRedirectUrl(response.redirect_on_success);
          setStatusDetails(
            `Your authorization with ${sourceMetadata.displayName} completed successfully.`
          );
        }
        setIsError(false);
      } catch (error) {
        console.error("OAuth error:", error);
        setStatusMessage("Oops, something went wrong!");
        setStatusDetails(
          "An error occurred during the OAuth process. Please try again."
        );
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
                Click{" "}
                <a href={redirectUrl} className="text-blue-500 underline">
                  here
                </a>{" "}
                to continue.
              </p>
            </div>
          )}
        </CardSection>
      </div>
    </div>
  );
}
