"use client";
import i18n from "@/i18n/init";
import k from "./../../../../../../i18n/keys";

import { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { AdminPageTitle } from "@/components/admin/Title";
import { Button } from "@/components/ui/button";
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
import { ErrorMessage, Field, Form, Formik, useFormikContext } from "formik";
import * as Yup from "yup";

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

  const [statusMessage, setStatusMessage] = useState("Обработка...");
  const [statusDetails, setStatusDetails] = useState(
    "Пожалуйста, подождите, пока мы завершим настройку."
  );
  const [redirectUrl, setRedirectUrl] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false); // New state
  const [pageTitle, setPageTitle] = useState(
    "Завершите авторизацию с помощью стороннего сервиса"
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
        setStatusMessage(
          "Неправильно сформированный запрос на завершение OAuth."
        );
        setStatusDetails(
          "Недействительный или отсутствующий идентификатор учетных данных."
        );
        setIsError(true);
        return;
      }

      const sourceType = connector.replaceAll("-", "_");
      if (!isValidSource(sourceType)) {
        setStatusMessage(
          `Указанный тип источника коннектора ${sourceType} не существует.`
        );
        setStatusDetails(
          `${sourceType} не является допустимым типом источника.`
        );
        setIsError(true);
        return;
      }

      const sourceMetadata = getSourceMetadata(sourceType as ValidSources);
      setPageTitle(
        `Завершить авторизацию с помощью ${sourceMetadata.displayName}`
      );

      setStatusMessage("Обработка...");
      setStatusDetails(
        "Пожалуйста, подождите, пока мы получим список доступных вам сайтов."
      );
      setIsError(false); // Ensure no error state during loading

      try {
        const response = await handleOAuthPrepareFinalization(
          connector,
          credential
        );

        if (!response) {
          throw new Error("Пустой ответ от сервера OAuth.");
        }

        setAccessibleResources(response.accessible_resources);

        setStatusMessage("Выберите сайт Confluence");
        setStatusDetails("");

        setIsError(false);
      } catch (error) {
        console.error("Ошибка завершения OAuth:", error);
        setStatusMessage("Упс, что-то пошло не так!");
        setStatusDetails(
          "Во время процесса завершения OAuth произошла ошибка. Повторите попытку."
        );
        setIsError(true);
      }
    };

    onFirstLoad();
  }, [credential, connector]);

  useEffect(() => {}, [redirectUrl]);

  return (
    <div className="mx-auto h-screen flex flex-col">
      <AdminPageTitle title={pageTitle} icon={<KeyIcon size={32} />} />

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
                "Требуется идентификатор учетных данных."
              ),
              cloud_id: Yup.string().required(
                "Вы должны выбрать сайт Confluence (id не найден)."
              ),
              cloud_name: Yup.string().required(
                "Вы должны выбрать сайт Confluence (имя не найдено)."
              ),
              cloud_url: Yup.string().required(
                "Вы должны выбрать сайт Confluence (url не найден)."
              ),
            })}
            validateOnMount
            onSubmit={async (values, formikHelpers) => {
              formikHelpers.setSubmitting(true);
              try {
                if (!values.cloud_id) {
                  throw new Error("Требуется идентификатор облака.");
                }
                if (!values.cloud_name) {
                  throw new Error("Облачный URL-адрес обязателен.");
                }

                if (!values.cloud_url) {
                  throw new Error("Облачный URL-адрес обязателен.");
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
                  setStatusMessage("Авторизация Confluence завершена.");
                }

                setIsSubmitted(true); // Отметить как отправленное
              } catch (error) {
                console.error(error);
                setStatusMessage("Ошибка во время отправки.");
                setStatusDetails(
                  "Во время отправки произошла ошибка. Попробуйте еще раз."
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
                  <Button
                    type="submit"
                    size="sm"
                    variant="submit"
                    disabled={!isValid || isSubmitting}
                  >
                    {isSubmitting ? i18n.t(k.SUBMITTING) : i18n.t(k.SUBMIT1)}
                  </Button>
                )}
              </Form>
            )}
          </Formik>

          {redirectUrl && !isError && (
            <div className="mt-4">
              <p className="text-sm">
                {i18n.t(k.AUTHORIZATION_FINALIZED_CLICK)}{" "}
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
