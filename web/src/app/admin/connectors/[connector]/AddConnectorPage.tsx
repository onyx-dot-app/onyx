"use client";

import * as Yup from "yup";
import { TrashIcon } from "@/components/icons/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";
import { HealthCheckBanner } from "@/components/health/healthcheck";

import { Card, Divider, Title } from "@tremor/react";
import { AdminPageTitle } from "@/components/admin/Title";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useFormContext } from "@/components/context/FormContext";
import { getSourceDisplayName } from "@/lib/sources";
import { SourceIcon } from "@/components/SourceIcon";
import { useRef, useState, useEffect } from "react";
import { submitConnector } from "@/components/admin/connectors/ConnectorForm";
import { deleteCredential, linkCredential } from "@/lib/credential";
import { submitFiles } from "./pages/utils/files";
import { submitGoogleSite } from "./pages/utils/google_site";
import AdvancedFormPage from "./pages/Advanced";
import DynamicConnectionForm from "./pages/DynamicConnectorCreationForm";
import CreateCredential from "@/components/credentials/actions/CreateCredential";
import ModifyCredential from "@/components/credentials/actions/ModifyCredential";
import { ConfigurableSources, ValidSources } from "@/lib/types";
import { Credential, credentialTemplates } from "@/lib/connectors/credentials";
import {
  ConnectionConfiguration,
  connectorConfigs,
} from "@/lib/connectors/connectors";
import { Modal } from "@/components/Modal";
import { ArrowRight } from "@phosphor-icons/react";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";
import { FiPlus } from "react-icons/fi";
import GDriveMain from "./pages/gdrive/GoogleDrivePage";
import { GmailMain } from "./pages/gmail/GmailPage";
import {
  useGmailCredentials,
  useGoogleDriveCredentials,
} from "./pages/utils/hooks";
import { Formik, FormikProps } from "formik";
import {
  IsPublicGroupSelector,
  IsPublicGroupSelectorFormType,
} from "@/components/IsPublicGroupSelector";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";

export type AdvancedConfigFinal = {
  pruneFreq: number | null;
  refreshFreq: number | null;
  indexingStart: Date | null;
};

export default function AddConnector({
  connector,
}: {
  connector: ConfigurableSources;
}) {
  const [currentCredential, setCurrentCredential] =
    useState<Credential<any> | null>(null);

  const { data: credentials } = useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(connector),
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );

  const { data: editableCredentials } = useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(connector, true),
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);

  const credentialTemplate = credentialTemplates[connector];

  const {
    setFormStep,
    setAllowAdvanced,
    setAlowCreate,
    formStep,
    nextFormStep,
    prevFormStep,
  } = useFormContext();

  const { popup, setPopup } = usePopup();

  const configuration: ConnectionConfiguration = connectorConfigs[connector];
  const [formValues, setFormValues] = useState<
    Record<string, any> & IsPublicGroupSelectorFormType
  >({
    name: "",
    groups: [],
    is_public: true,
    ...configuration.values.reduce(
      (acc, field) => {
        if (field.type === "select") {
          acc[field.name] = null;
        } else if (field.type === "list") {
          acc[field.name] = field.default || [];
        } else if (field.type === "checkbox") {
          acc[field.name] = field.default || false;
        } else if (field.default !== undefined) {
          acc[field.name] = field.default;
        }
        return acc;
      },
      {} as { [record: string]: any }
    ),
  });

  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  // Default to 10 minutes unless otherwise specified
  const defaultAdvancedSettings = {
    refreshFreq: formValues.overrideDefaultFreq || 10,
    pruneFreq: 30,
    indexingStart: null as string | null,
  };

  const [advancedSettings, setAdvancedSettings] = useState(
    defaultAdvancedSettings
  );

  const [createConnectorToggle, setCreateConnectorToggle] = useState(false);
  const formRef = useRef<FormikProps<any>>(null);

  const [isFormValid, setIsFormValid] = useState(false);

  const handleFormStatusChange = (isValid: boolean) => {
    setIsFormValid(isValid || connector == "file");
  };

  const { liveGDriveCredential } = useGoogleDriveCredentials();

  const { liveGmailCredential } = useGmailCredentials();

  const credentialActivated =
    (connector === "google_drive" && liveGDriveCredential) ||
    (connector === "gmail" && liveGmailCredential) ||
    currentCredential;

  const noCredentials = credentialTemplate == null;

  if (noCredentials && 1 != formStep) {
    setFormStep(Math.max(1, formStep));
  }

  if (!noCredentials && !credentialActivated && formStep != 0) {
    setFormStep(Math.min(formStep, 0));
  }

  const resetAdvancedConfigs = (formikProps: FormikProps<any>) => {
    formikProps.resetForm({ values: defaultAdvancedSettings });
    setAdvancedSettings(defaultAdvancedSettings);
  };

  const convertStringToDateTime = (indexingStart: string | null) => {
    return indexingStart ? new Date(indexingStart) : null;
  };

  const createConnector = async () => {
    const {
      name,
      groups,
      is_public: isPublic,
      ...connector_specific_config
    } = formValues;
    const { pruneFreq, indexingStart, refreshFreq } = advancedSettings;

    // Apply transforms from connectors.ts configuration
    const transformedConnectorSpecificConfig = Object.entries(
      connector_specific_config
    ).reduce(
      (acc, [key, value]) => {
        const matchingConfigValue = configuration.values.find(
          (configValue) => configValue.name === key
        );
        if (
          matchingConfigValue &&
          "transform" in matchingConfigValue &&
          matchingConfigValue.transform
        ) {
          acc[key] = matchingConfigValue.transform(value as string[]);
        } else {
          acc[key] = value;
        }
        return acc;
      },
      {} as Record<string, any>
    );

    const AdvancedConfig: AdvancedConfigFinal = {
      pruneFreq: advancedSettings.pruneFreq * 60 * 60 * 24,
      indexingStart: convertStringToDateTime(indexingStart),
      refreshFreq: advancedSettings.refreshFreq * 60,
    };

    // google sites-specific handling
    if (connector == "google_sites") {
      const response = await submitGoogleSite(
        selectedFiles,
        formValues?.base_url,
        setPopup,
        AdvancedConfig,
        name
      );
      if (response) {
        setTimeout(() => {
          window.open("/admin/indexing/status", "_self");
        }, 1000);
      }
      return;
    }

    // file-specific handling
    if (connector == "file" && selectedFiles.length > 0) {
      const response = await submitFiles(
        selectedFiles,
        setPopup,
        setSelectedFiles,
        name,
        AdvancedConfig,
        isPublic,
        groups
      );
      if (response) {
        setTimeout(() => {
          window.open("/admin/indexing/status", "_self");
        }, 1000);
      }
      return;
    }

    const { message, isSuccess, response } = await submitConnector<any>(
      {
        connector_specific_config: transformedConnectorSpecificConfig,
        input_type: connector == "web" ? "load_state" : "poll", // single case
        name: name,
        source: connector,
        refresh_freq: refreshFreq * 60 || null,
        prune_freq: pruneFreq * 60 * 60 * 24 || null,
        indexing_start: convertStringToDateTime(indexingStart),
        is_public: isPublic,
        groups: groups,
      },
      undefined,
      credentialActivated ? false : true,
      isPublic
    );
    // If no credential
    if (!credentialActivated) {
      if (isSuccess) {
        setPopup({
          message: "Connector created! Redirecting to connector home page",
          type: "success",
        });
        setTimeout(() => {
          window.open("/admin/indexing/status", "_self");
        }, 1000);
      } else {
        setPopup({ message: message, type: "error" });
      }
    }

    // Without credential
    if (credentialActivated && isSuccess && response) {
      const credential =
        currentCredential || liveGDriveCredential || liveGmailCredential;
      const linkCredentialResponse = await linkCredential(
        response.id,
        credential?.id!,
        name,
        isPublic,
        groups
      );
      if (linkCredentialResponse.ok) {
        setPopup({
          message: "Connector created! Redirecting to connector home page",
          type: "success",
        });
        setTimeout(() => {
          window.open("/admin/indexing/status", "_self");
        }, 1000);
      } else {
        const errorData = await linkCredentialResponse.json();
        setPopup({
          message: errorData.message,
          type: "error",
        });
      }
    } else if (isSuccess) {
      setPopup({
        message:
          "Credential created succsfully! Redirecting to connector home page",
        type: "success",
      });
    } else {
      setPopup({ message: message, type: "error" });
    }
  };

  const displayName = getSourceDisplayName(connector) || connector;
  if (!credentials || !editableCredentials) {
    return <></>;
  }

  const refresh = () => {
    mutate(buildSimilarCredentialInfoURL(connector));
  };
  const onDeleteCredential = async (credential: Credential<any | null>) => {
    const response = await deleteCredential(credential.id, true);
    if (response.ok) {
      setPopup({
        message: "Credential deleted successfully!",
        type: "success",
      });
    } else {
      const errorData = await response.json();
      setPopup({
        message: errorData.message,
        type: "error",
      });
    }
  };

  const onSwap = async (selectedCredential: Credential<any>) => {
    setCurrentCredential(selectedCredential);
    setAlowCreate(true);
    setPopup({
      message: "Swapped credential successfully!",
      type: "success",
    });
    refresh();
  };

  const validationSchema = Yup.object().shape({
    name: Yup.string().required("Connector Name is required"),
    ...configuration.values.reduce(
      (acc, field) => {
        let schema: any =
          field.type === "select"
            ? Yup.string()
            : field.type === "list"
              ? Yup.array().of(Yup.string())
              : field.type === "checkbox"
                ? Yup.boolean()
                : Yup.string();

        if (!field.optional) {
          schema = schema.required(`${field.label} is required`);
        }
        acc[field.name] = schema;
        return acc;
      },
      {} as Record<string, any>
    ),
  });

  const advancedValidationSchema = Yup.object().shape({
    indexingStart: Yup.string().nullable(),
    pruneFreq: Yup.number().min(0, "Prune frequency must be non-negative"),
    refreshFreq: Yup.number().min(0, "Refresh frequency must be non-negative"),
  });

  const isFormSubmittable = (values: any) => {
    return (
      values.name.trim() !== "" &&
      Object.keys(values).every((key) => {
        const field = configuration.values.find((f) => f.name === key);
        return field?.optional || values[key] !== "";
      })
    );
  };

  return (
    <div className="mx-auto mb-8 w-full">
      {popup}
      <div className="mb-4">
        <HealthCheckBanner />
      </div>

      <AdminPageTitle
        includeDivider={false}
        icon={<SourceIcon iconSize={32} sourceType={connector} />}
        title={displayName}
      />

      {formStep == 0 &&
        (connector == "google_drive" ? (
          <>
            <Card>
              <Title className="mb-2 text-lg">Select a credential</Title>
              <GDriveMain />
            </Card>
            <div className="mt-4 flex w-full justify-end">
              <button
                className="enabled:cursor-pointer disabled:bg-blue-200 bg-blue-400 flex gap-x-1 items-center text-white py-2.5 px-3.5 text-sm font-regular rounded-sm"
                disabled={!credentialActivated}
                onClick={() => nextFormStep()}
              >
                Continue
                <ArrowRight />
              </button>
            </div>
          </>
        ) : connector == "gmail" ? (
          <>
            <Card>
              <Title className="mb-2 text-lg">Select a credential</Title>
              <GmailMain />
            </Card>
            <div className="mt-4 flex w-full justify-end">
              <button
                className="enabled:cursor-pointer disabled:bg-blue-200 bg-blue-400 flex gap-x-1 items-center text-white py-2.5 px-3.5 text-sm font-regular rounded-sm"
                disabled={!credentialActivated}
                onClick={() => nextFormStep()}
              >
                Continue
                <ArrowRight />
              </button>
            </div>
          </>
        ) : (
          <>
            <Card>
              <Title className="mb-2 text-lg">Select a credential</Title>
              <ModifyCredential
                showIfEmpty
                source={connector}
                defaultedCredential={currentCredential!}
                credentials={credentials}
                editableCredentials={editableCredentials}
                onDeleteCredential={onDeleteCredential}
                onSwitch={onSwap}
              />
              {!createConnectorToggle && (
                <button
                  className="mt-6 text-sm bg-background-900 px-2 py-1.5 flex text-text-200 flex-none rounded"
                  onClick={() =>
                    setCreateConnectorToggle(
                      (createConnectorToggle) => !createConnectorToggle
                    )
                  }
                >
                  Create New
                </button>
              )}

              {/* NOTE: connector will never be google_drive, since the ternary above will 
              prevent that, but still keeping this here for safety in case the above changes. */}
              {(connector as ValidSources) !== "google_drive" &&
                createConnectorToggle && (
                  <Modal
                    className="max-w-3xl rounded-lg"
                    onOutsideClick={() => setCreateConnectorToggle(false)}
                  >
                    <>
                      <Title className="mb-2 text-lg">
                        Create a {getSourceDisplayName(connector)} credential
                      </Title>
                      <CreateCredential
                        close
                        refresh={refresh}
                        sourceType={connector}
                        setPopup={setPopup}
                        onSwitch={onSwap}
                        onClose={() => setCreateConnectorToggle(false)}
                      />
                    </>
                  </Modal>
                )}
            </Card>
            <div className="mt-4 flex w-full justify-end">
              <button
                className="enabled:cursor-pointer disabled:cursor-not-allowed disabled:bg-blue-200 bg-blue-400 flex gap-x-1 items-center text-white py-2.5 px-3.5 text-sm font-regular rounded-sm"
                disabled={currentCredential == null}
                onClick={() => nextFormStep()}
              >
                Continue
                <ArrowRight />
              </button>
            </div>
          </>
        ))}

      {formStep == 1 && (
        <>
          <Card>
            <Formik
              initialValues={formValues}
              validationSchema={validationSchema}
              onSubmit={() => {
                // Can be utilized for logging purposes
              }}
            >
              {(formikProps) => {
                setFormValues(formikProps.values);
                handleFormStatusChange(
                  formikProps.isValid && isFormSubmittable(formikProps.values)
                );
                setAllowAdvanced(
                  formikProps.isValid && isFormSubmittable(formikProps.values)
                );

                return (
                  <div className="w-full py-4 flex gap-y-6 flex-col max-w-2xl mx-auto">
                    <DynamicConnectionForm
                      values={formikProps.values}
                      config={configuration}
                      setSelectedFiles={setSelectedFiles}
                      selectedFiles={selectedFiles}
                    />
                    {isPaidEnterpriseFeaturesEnabled && (
                      <>
                        <IsPublicGroupSelector
                          removeIndent
                          formikProps={formikProps}
                          objectName="Connector"
                        />
                      </>
                    )}
                  </div>
                );
              }}
            </Formik>
          </Card>
          <div className={`mt-4 w-full grid grid-cols-3`}>
            {!noCredentials ? (
              <button
                className="border-border-dark mr-auto border flex gap-x-1 items-center text-text p-2.5 text-sm font-regular rounded-sm "
                onClick={() => prevFormStep()}
              >
                <ArrowLeft />
                Previous
              </button>
            ) : (
              <div />
            )}
            <button
              className="enabled:cursor-pointer ml-auto disabled:bg-accent/50 disabled:cursor-not-allowed bg-accent flex mx-auto gap-x-1 items-center text-white py-2.5 px-3.5 text-sm font-regular rounded-sm"
              disabled={
                !isFormValid ||
                (connector == "file" && selectedFiles.length == 0)
              }
              onClick={async () => {
                await createConnector();
              }}
            >
              Create Connector
              <FiPlus className="text-white h-4 w-4" />
            </button>

            {!(connector == "file") && (
              <div className="flex w-full justify-end">
                <button
                  className={`enabled:cursor-pointer enabled:hover:underline disabled:cursor-not-allowed mt-auto enabled:text-text-600 disabled:text-text-400 ml-auto flex gap-x-1 items-center py-2.5 px-3.5 text-sm font-regular rounded-sm`}
                  disabled={!isFormValid}
                  onClick={() => {
                    nextFormStep();
                  }}
                >
                  Advanced
                  <ArrowRight />
                </button>
              </div>
            )}
          </div>
        </>
      )}

      {formStep === 2 && (
        <>
          <Card>
            <Formik
              initialValues={advancedSettings}
              validationSchema={advancedValidationSchema}
              onSubmit={() => {}}
            >
              {(formikProps) => {
                setAdvancedSettings(formikProps.values);

                return (
                  <>
                    <AdvancedFormPage formikProps={formikProps} ref={formRef} />
                    <div className="mt-4 flex w-full mx-auto max-w-2xl justify-start">
                      <button
                        className="flex gap-x-1 bg-red-500 hover:bg-red-500/80 items-center text-white py-2.5 px-3.5 text-sm font-regular rounded "
                        onClick={() => resetAdvancedConfigs(formikProps)}
                      >
                        <TrashIcon size={20} className="text-white" />
                        <div className="w-full items-center gap-x-2 flex">
                          Reset
                        </div>
                      </button>
                    </div>
                  </>
                );
              }}
            </Formik>
          </Card>
          <div className={`mt-4 grid grid-cols-3 w-full `}>
            <button
              className="border-border-dark border mr-auto flex gap-x-1 items-center text-text py-2.5 px-3.5 text-sm font-regular rounded-sm"
              onClick={() => prevFormStep()}
            >
              <ArrowLeft />
              Previous
            </button>
            <button
              className="enabled:cursor-pointer ml-auto disabled:bg-accent/50 bg-accent flex mx-auto gap-x-1 items-center text-white py-2.5 px-3.5 text-sm font-regular rounded-sm"
              onClick={async () => {
                await createConnector();
              }}
            >
              Create Connector
              <FiPlus className="text-white h-4 w-4" />
            </button>
          </div>
        </>
      )}
    </div>
  );
}
