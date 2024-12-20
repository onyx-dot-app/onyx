"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { AdminPageTitle } from "@/components/admin/Title";
import { Button } from "@/components/ui/button";
import Title from "@/components/ui/title";
import { KeyIcon } from "@/components/icons/icons";
import { getSourceMetadata, isValidSource } from "@/lib/sources";
import { ConfluenceAccessibleResource, ValidSources } from "@/lib/types";
import CardSection from "@/components/admin/CardSection";
import {
  handleOAuthAuthorizationResponse,
  handleOAuthConfluenceFinalize,
  handleOAuthPrepareFinalization,
} from "@/lib/oauth_utils";
import { SelectorFormField } from "@/components/admin/connectors/Field";
import { Form, Formik } from "formik";
import * as Yup from "yup";

export default function OAuthFinalizePage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [statusMessage, setStatusMessage] = useState("Processing...");
  const [statusDetails, setStatusDetails] = useState(
    "Please wait while we complete the setup."
  );
  const [redirectUrl, setRedirectUrl] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false); // New state
  const [pageTitle, setPageTitle] = useState(
    "Finalize Authorization with Third-Party service"
  );

  const [accessibleResources, setAccessibleResources] = useState<
    ConfluenceAccessibleResource[]
  >([]);

  // Extract query parameters
  const credentialParam = searchParams.get("credential");
  const credential = credentialParam ? parseInt(credentialParam, 10) : NaN;
  const pathname = usePathname();
  const connector = pathname?.split("/")[3];

  useEffect(() => {
    const onFirstLoad = async () => {
      // Examples
      // connector (url segment)= "google-drive"
      // sourceType (for looking up metadata) = "google_drive"

      if (isNaN(credential)) {
        setStatusMessage("Improperly formed OAuth finalization request.");
        setStatusDetails("Invalid or missing credential id.");
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
      setPageTitle(`Finalize Authorization with ${sourceMetadata.displayName}`);

      setStatusMessage("Processing...");
      setStatusDetails(
        "Please wait while we retrieve a list of your accessible sites."
      );
      setIsError(false); // Ensure no error state during loading

      try {
        const response = await handleOAuthPrepareFinalization(
          connector,
          credential
        );

        if (!response) {
          throw new Error("Empty response from OAuth server.");
        }

        setAccessibleResources(response.accessible_resources);

        setStatusMessage("Select a Confluence site");
        setStatusDetails("");

        setIsError(false);
      } catch (error) {
        console.error("OAuth finalization error:", error);
        setStatusMessage("Oops, something went wrong!");
        setStatusDetails(
          "An error occurred during the OAuth finalization process. Please try again."
        );
        setIsError(true);
      }
    };

    onFirstLoad();
  }, [credential, connector]);

  useEffect(() => {}, [redirectUrl]);

  return (
    <div className="container mx-auto py-8">
      <AdminPageTitle title={pageTitle} icon={<KeyIcon size={32} />} />

      <div className="flex flex-col items-center justify-center min-h-screen">
        <CardSection className="max-w-md">
          <h1 className="text-2xl font-bold mb-4">{statusMessage}</h1>
          <p className="text-text-500">{statusDetails}</p>

          <Formik
            initialValues={{
              credential_id: credential,
              cloud_id: null,
            }}
            validationSchema={Yup.object().shape({
              credential_id: Yup.number().required(
                "Credential ID is required."
              ),
              cloud_id: Yup.string().required(
                "You must select a Confluence site."
              ),
            })}
            validateOnMount
            onSubmit={async (values, formikHelpers) => {
              formikHelpers.setSubmitting(true);
              try {
                if (!values.cloud_id) {
                  throw new Error("Cloud ID is required.");
                }

                const response = await handleOAuthConfluenceFinalize(
                  values.credential_id,
                  values.cloud_id
                );
                formikHelpers.setSubmitting(false);

                if (response) {
                  setRedirectUrl(response.redirect_url);
                  setStatusMessage("Confluence authorization finalized.");
                }

                setIsSubmitted(true); // Mark as submitted
              } catch (error) {
                console.error(error);
                setStatusMessage("Error during submission.");
                setStatusDetails(
                  "An error occurred during the submission process. Please try again."
                );
                setIsError(true);
                formikHelpers.setSubmitting(false);
              }
            }}
          >
            {({ isSubmitting, isValid, setFieldValue }) => (
              <Form>
                {!redirectUrl && accessibleResources.length > 0 && (
                  <SelectorFormField
                    name="cloud_id"
                    options={accessibleResources.map((resource) => ({
                      name: `${resource.name} - ${resource.url}`,
                      value: resource.id,
                    }))}
                    onSelect={(selected) => {
                      setFieldValue("cloud_id", selected);
                    }}
                  />
                )}
                {!redirectUrl && (
                  <Button
                    type="submit"
                    size="sm"
                    variant="submit"
                    disabled={!isValid || isSubmitting}
                  >
                    {isSubmitting ? "Submitting..." : "Submit"}
                  </Button>
                )}
              </Form>
            )}
          </Formik>

          {redirectUrl && !isError && (
            <div className="mt-4">
              <p className="text-sm">
                Authorization finalized. Click{" "}
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
