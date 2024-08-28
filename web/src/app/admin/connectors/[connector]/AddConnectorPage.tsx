"use client";

import { TrashIcon } from "@/components/icons/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";
import { HealthCheckBanner } from "@/components/health/healthcheck";

import { Card, Title } from "@tremor/react";
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
import DynamicConnectionForm from "./pages/Create";
import CreateCredential from "@/components/credentials/actions/CreateCredential";
import ModifyCredential from "@/components/credentials/actions/ModifyCredential";
import { ValidSources } from "@/lib/types";
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
import { FormikProps } from "formik";
import { useUser } from "@/components/user/UserProvider";

export type AdvancedConfig = {
  pruneFreq: number | null;
  refreshFreq: number | null;
  indexingStart: Date | null;
};

export default function AddConnector({
  connector,
}: {
  connector: ValidSources;
}) {
  const [name, setName] = useState("");
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

  const { setFormStep, setAlowCreate, formStep, nextFormStep, prevFormStep } =
    useFormContext();

  const { popup, setPopup } = usePopup();

  const configuration: ConnectionConfiguration = connectorConfigs[connector];

  const initialValues = configuration.values.reduce(
    (acc, field) => {
      if (field.type === "list") {
        acc[field.name] = field.default || [];
      } else if (field.default !== undefined) {
        acc[field.name] = field.default;
      }
      return acc;
    },
    {} as { [record: string]: any }
  );

  const [values, setValues] = useState<{ [record: string]: any } | null>(
    Object.keys(initialValues).length > 0 ? initialValues : null
  );

  // Default to 10 minutes unless otherwise specified
  const defaultRefresh = configuration.overrideDefaultFreq || 10;
  // Default is 30 days
  const defaultPrune = 30;

  const [refreshFreq, setRefreshFreq] = useState<number>(defaultRefresh || 0);
  const [pruneFreq, setPruneFreq] = useState<number>(defaultPrune);
  const [indexingStart, setIndexingStart] = useState<Date | null>(null);
  const { isAdmin, isLoadingUser } = useUser();

  const [isPublic, setIsPublic] = useState(isAdmin);
  useEffect(() => {
    if (!isLoadingUser) {
      setIsPublic(isAdmin);
    }
  }, [isLoadingUser, isAdmin]);

  const [groups, setGroups] = useState<number[]>([]);
  const [createConnectorToggle, setCreateConnectorToggle] = useState(false);
  const formRef = useRef<FormikProps<any>>(null);
  const [advancedFormPageState, setAdvancedFormPageState] = useState(true);

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

  if (isLoadingUser) {
    return <></>;
  }

  const resetAdvancedConfigs = () => {
    const resetRefreshFreq = defaultRefresh || 0;
    const resetPruneFreq = defaultPrune;
    const resetIndexingStart = null;

    setRefreshFreq(resetRefreshFreq);
    setPruneFreq(resetPruneFreq);
    setIndexingStart(resetIndexingStart);
    setAdvancedFormPageState((advancedFormPageState) => !advancedFormPageState);
    // Update the form values
    if (formRef.current) {
      formRef.current.setFieldValue("refreshFreq", resetRefreshFreq);
      formRef.current.setFieldValue("pruneFreq", resetPruneFreq);
      formRef.current.setFieldValue("indexingStart", resetIndexingStart);
    }
  };

  const createConnector = async () => {
    const AdvancedConfig: AdvancedConfig = {
      pruneFreq: pruneFreq * 60 * 60 * 24,
      indexingStart,
      refreshFreq: refreshFreq * 60,
    };

    // google sites-specific handling
    if (connector == "google_site") {
      const response = await submitGoogleSite(
        selectedFiles,
        values?.base_url,
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
        connector_specific_config: values,
        input_type: connector == "web" ? "load_state" : "poll", // single case
        name: name,
        source: connector,
        refresh_freq: refreshFreq * 60 || null,
        prune_freq: pruneFreq * 60 * 60 * 24 || null,
        indexing_start: indexingStart,
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

  const updateValues = (field: string, value: any) => {
    if (field == "name") {
      return;
    }
    setValues((values) => {
      if (!values) {
        return { [field]: value };
      } else {
        return { ...values, [field]: value };
      }
    });
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

              {!(connector == "google_drive") && createConnectorToggle && (
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
            <DynamicConnectionForm
              setSelectedFiles={setSelectedFiles}
              selectedFiles={selectedFiles}
              setIsPublic={setIsPublic}
              updateValues={updateValues}
              setName={setName}
              config={configuration}
              isPublic={isPublic}
              groups={groups}
              setGroups={setGroups}
              defaultValues={values}
              initialName={name}
              onFormStatusChange={handleFormStatusChange}
            />
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
            <AdvancedFormPage
              key={advancedFormPageState ? 0 : 1}
              setIndexingStart={setIndexingStart}
              indexingStart={indexingStart}
              setPruneFreq={setPruneFreq}
              currentPruneFreq={pruneFreq}
              setRefreshFreq={setRefreshFreq}
              currentRefreshFreq={refreshFreq}
              ref={formRef}
            />

            <div className="mt-4 flex w-full mx-auto max-w-2xl justify-start">
              <button
                className="flex gap-x-1 bg-red-500 hover:bg-red-500/80 items-center text-white py-2.5 px-3.5 text-sm font-regular rounded "
                onClick={() => resetAdvancedConfigs()}
              >
                <TrashIcon size={20} className="text-white" />
                <div className="w-full items-center gap-x-2 flex">Reset</div>
              </button>
            </div>
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
