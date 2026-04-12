"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { AdminPageTitle } from "@/components/admin/Title";
import { Button } from "@opal/components";
import { getSourceMetadata, isValidSource } from "@/lib/sources";
import { ConfluenceAccessibleResource, ValidSources } from "@/lib/types";
import CardSection from "@/components/admin/CardSection";
import {
  handleOAuthConfluenceFinalize,
  handleOAuthPrepareFinalization,
} from "@/lib/oauth_utils";
import { SelectorFormField } from "@/components/Field";
import { ErrorMessage, Field, Form, Formik, useFormikContext } from "formik";
import * as Yup from "yup";
import { SvgKey } from "@opal/icons";
// Helper component to keep the effect logic clean:
function UpdateCloudURLOnCloudIdChange({
  accessibleResources,
}: {
  accessibleResources: ConfluenceAccessibleResource[];
}) {
  const { values, setValues, setFieldValue } = useFormikContext<{
    cloud_id: string;
    cloud_name: string;
    cloud_url: string;
  }>();

  useEffect(() => {
    // Whenever cloud_id changes, find the matching resource and update cloud_url
    if (values.cloud_id) {
      const selectedResource = accessibleResources.find(
        (resource) => resource.id === values.cloud_id
      );
      if (selectedResource) {
        // Update multiple fields together ... somehow setting them in sequence
        // doesn't work with the validator
        // it may also be possible to await each setFieldValue call.
        // https://github.com/jaredpalmer/formik/issues/2266
        setValues((prevValues) => ({
          ...prevValues,
          cloud_name: selectedResource.name,
          cloud_url: selectedResource.url,
        }));
      }
    }
  }, [values.cloud_id, accessibleResources, setFieldValue]);

  // This component doesn't render anything visible:
  return null;
}

export default function OAuthFinalizePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const t = useTranslations("admin.oauth");
  const tc = useTranslations("common");

  const [statusMessage, setStatusMessage] = useState(t("processing"));
  const [statusDetails, setStatusDetails] = useState(
    t("pleaseWaitSetup")
  );
  const [redirectUrl, setRedirectUrl] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false); // New state
  const [pageTitle, setPageTitle] = useState(
    t("finalizeAuthWithThirdParty")
  );

  const [accessibleResources, setAccessibleResources] = useState<
    ConfluenceAccessibleResource[]
  >([]);

  // Extract query parameters
  const credentialParam = searchParams?.get("credential");
  const credential = credentialParam ? parseInt(credentialParam, 10) : NaN;
  const pathname = usePathname();
  const connector = pathname?.split("/")[3];

  useEffect(() => {
    const onFirstLoad = async () => {
      // Examples
      // connector (url segment)= "google-drive"
      // sourceType (for looking up metadata) = "google_drive"

      if (isNaN(credential) || !connector) {
        setStatusMessage(t("improperlyFormedFinalization"));
        setStatusDetails(t("invalidOrMissingCredentialId"));
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
      setPageTitle(t("finalizeAuthWith", { provider: sourceMetadata.displayName }));

      setStatusMessage(t("processing"));
      setStatusDetails(
        t("pleaseWaitRetrieveSites")
      );
      setIsError(false); // Ensure no error state during loading

      try {
        const response = await handleOAuthPrepareFinalization(
          connector,
          credential
        );

        if (!response) {
          throw new Error(t("emptyResponse"));
        }

        setAccessibleResources(response.accessible_resources);

        setStatusMessage(t("selectConfluenceSite"));
        setStatusDetails("");

        setIsError(false);
      } catch (error) {
        console.error("OAuth finalization error:", error);
        setStatusMessage(t("oopsWrong"));
        setStatusDetails(
          t("oauthFinalizationError")
        );
        setIsError(true);
      }
    };

    onFirstLoad();
  }, [credential, connector]);

  useEffect(() => {}, [redirectUrl]);

  return (
    <div className="mx-auto h-screen flex flex-col">
      <AdminPageTitle title={pageTitle} icon={SvgKey} />

      <div className="flex-1 flex flex-col items-center justify-center">
        <CardSection className="max-w-md w-[500px] h-[250px] p-8">
          <h1 className="text-2xl font-bold mb-4">{statusMessage}</h1>
          <p className="text-text-500">{statusDetails}</p>

          <Formik
            initialValues={{
              credential_id: credential,
              cloud_id: "",
              cloud_name: "",
              cloud_url: "",
            }}
            validationSchema={Yup.object().shape({
              credential_id: Yup.number().required(
                t("credentialIdRequired")
              ),
              cloud_id: Yup.string().required(
                t("mustSelectSiteId")
              ),
              cloud_name: Yup.string().required(
                t("mustSelectSiteName")
              ),
              cloud_url: Yup.string().required(
                t("mustSelectSiteUrl")
              ),
            })}
            validateOnMount
            onSubmit={async (values, formikHelpers) => {
              formikHelpers.setSubmitting(true);
              try {
                if (!values.cloud_id) {
                  throw new Error(t("cloudIdRequired"));
                }

                if (!values.cloud_name) {
                  throw new Error(t("cloudUrlRequired"));
                }

                if (!values.cloud_url) {
                  throw new Error(t("cloudUrlRequired"));
                }

                const response = await handleOAuthConfluenceFinalize(
                  values.credential_id,
                  values.cloud_id,
                  values.cloud_name,
                  values.cloud_url
                );
                formikHelpers.setSubmitting(false);

                if (response) {
                  setRedirectUrl(response.redirect_url);
                  setStatusMessage(t("confluenceAuthFinalized"));
                }

                setIsSubmitted(true); // Mark as submitted
              } catch (error) {
                console.error(error);
                setStatusMessage(t("errorDuringSubmission"));
                setStatusDetails(
                  t("submissionError")
                );
                setIsError(true);
                formikHelpers.setSubmitting(false);
              }
            }}
          >
            {({ isSubmitting, isValid, setFieldValue }) => (
              <Form>
                {/* Debug info
                <div className="mb-4 p-2 bg-gray-100 rounded text-xs">
                  <pre>
                    isValid: {String(isValid)}
                    errors: {JSON.stringify(errors, null, 2)}
                    values: {JSON.stringify(values, null, 2)}
                  </pre>
                </div> */}

                {/* Our helper component that reacts to changes in cloud_id */}
                <UpdateCloudURLOnCloudIdChange
                  accessibleResources={accessibleResources}
                />

                <Field type="hidden" name="cloud_name" />
                <ErrorMessage
                  name="cloud_name"
                  component="div"
                  className="error"
                />

                <Field type="hidden" name="cloud_url" />
                <ErrorMessage
                  name="cloud_url"
                  component="div"
                  className="error"
                />

                {!redirectUrl && accessibleResources.length > 0 && (
                  <SelectorFormField
                    name="cloud_id"
                    options={accessibleResources.map((resource) => ({
                      name: `${resource.name} - ${resource.url}`,
                      value: resource.id,
                    }))}
                    onSelect={(selectedValue) => {
                      const selectedResource = accessibleResources.find(
                        (resource) => resource.id === selectedValue
                      );
                      if (selectedResource) {
                        setFieldValue("cloud_id", selectedResource.id);
                      }
                    }}
                  />
                )}
                <br />
                {!redirectUrl && (
                  <Button disabled={!isValid || isSubmitting} type="submit">
                    {isSubmitting ? t("submitting") : tc("submit")}
                  </Button>
                )}
              </Form>
            )}
          </Formik>

          {redirectUrl && !isError && (
            <div className="mt-4">
              <p className="text-sm">
                {"Authorization finalized. Click "}<a href={redirectUrl} className="text-blue-500 underline">{t("clickHere")}</a>{" to continue."}
              </p>
            </div>
          )}
        </CardSection>
      </div>
    </div>
  );
}
