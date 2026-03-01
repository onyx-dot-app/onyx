"use client";

import { AccessType, ValidSources } from "@/lib/types";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useState } from "react";
import {
  deleteCredential,
  swapCredential,
  updateCredential,
  updateCredentialWithPrivateKey,
} from "@/lib/credential";
import { toast } from "@/hooks/useToast";
import CreateCredential from "./actions/CreateCredential";
import { CCPairFullInfo } from "@/app/admin/connector/[ccPairId]/types";
import ModifyCredential from "./actions/ModifyCredential";
import {
  buildCCPairInfoUrl,
  buildSimilarCredentialInfoURL,
} from "@/app/admin/connector/[ccPairId]/lib";
import Modal from "@/refresh-components/Modal";
import EditCredential from "./actions/EditCredential";
import { getSourceDisplayName } from "@/lib/sources";
import {
  ConfluenceCredentialJson,
  Credential,
} from "@/lib/connectors/credentials";
import {
  getConnectorOauthRedirectUrl,
  useOAuthDetails,
} from "@/lib/connectors/oauth";
import { Spinner } from "@/components/Spinner";
import CreateStdOAuthCredential from "@/components/credentials/actions/CreateStdOAuthCredential";
import Card from "@/refresh-components/cards/Card";
import { isTypedFileField, TypedFile } from "@/lib/connectors/fileTypes";
import { SvgEdit, SvgKey } from "@opal/icons";
import { LineItemLayout } from "@/layouts/general-layouts";
import { Button } from "@opal/components";

export interface CredentialSectionProps {
  ccPair: CCPairFullInfo;
  sourceType: ValidSources;
  refresh: () => void;
}

export default function CredentialSection({
  ccPair,
  sourceType,
  refresh,
}: CredentialSectionProps) {
  const { data: credentials } = useSWR<Credential<ConfluenceCredentialJson>[]>(
    buildSimilarCredentialInfoURL(sourceType),
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );
  const { data: editableCredentials } = useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(sourceType, true),
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );
  const { data: oauthDetails, isLoading: oauthDetailsLoading } =
    useOAuthDetails(sourceType);

  const makeShowCreateCredential = async () => {
    if (oauthDetailsLoading || !oauthDetails) {
      return;
    }

    if (oauthDetails.oauth_enabled) {
      if (oauthDetails.additional_kwargs.length > 0) {
        setShowCreateCredential(true);
      } else {
        const redirectUrl = await getConnectorOauthRedirectUrl(sourceType, {});
        if (redirectUrl) {
          window.location.href = redirectUrl;
        }
      }
    } else {
      setShowModifyCredential(false);
      setShowCreateCredential(true);
    }
  };

  const onSwap = async (
    selectedCredential: Credential<any>,
    connectorId: number,
    accessType: AccessType
  ) => {
    const response = await swapCredential(
      selectedCredential.id,
      connectorId,
      accessType
    );
    if (response.ok) {
      mutate(buildSimilarCredentialInfoURL(sourceType));
      refresh();

      toast.success("Swapped credential successfully!");
    } else {
      const errorData = await response.json();
      toast.error(
        `Issue swapping credential: ${
          errorData.detail || errorData.message || "Unknown error"
        }`
      );
    }
  };

  const onUpdateCredential = async (
    selectedCredential: Credential<any | null>,
    details: any,
    onSucces: () => void
  ) => {
    let privateKey: TypedFile | null = null;
    Object.entries(details).forEach(([key, value]) => {
      if (isTypedFileField(key)) {
        privateKey = value as TypedFile;
        delete details[key];
      }
    });
    let response;
    if (privateKey) {
      response = await updateCredentialWithPrivateKey(
        selectedCredential.id,
        details,
        privateKey
      );
    } else {
      response = await updateCredential(selectedCredential.id, details);
    }
    if (response.ok) {
      toast.success("Updated credential");
      onSucces();
    } else {
      toast.error("Issue updating credential");
    }
  };

  const onEditCredential = (credential: Credential<any>) => {
    closeModifyCredential();
    setEditingCredential(credential);
  };

  const onDeleteCredential = async (credential: Credential<any | null>) => {
    await deleteCredential(credential.id, true);
    mutate(buildCCPairInfoUrl(ccPair.id));
  };
  const defaultedCredential = ccPair.credential;

  const [showModifyCredential, setShowModifyCredential] = useState(false);
  const [showCreateCredential, setShowCreateCredential] = useState(false);
  const [editingCredential, setEditingCredential] =
    useState<Credential<any> | null>(null);

  const closeModifyCredential = () => {
    setShowModifyCredential(false);
  };

  const closeCreateCredential = () => {
    setShowCreateCredential(false);
  };

  const closeEditingCredential = () => {
    setEditingCredential(null);
    setShowModifyCredential(true);
  };
  if (!credentials || !editableCredentials) {
    return <></>;
  }

  return (
    <>
      {showModifyCredential && (
        <Modal open onOpenChange={closeModifyCredential}>
          <Modal.Content>
            <Modal.Header
              icon={SvgEdit}
              title="Update Credentials"
              description="Select a credential as needed! Ensure that you have selected a credential with the proper permissions for this connector!"
              onClose={closeModifyCredential}
            />
            <ModifyCredential
              close={closeModifyCredential}
              accessType={ccPair.access_type}
              attachedConnector={ccPair.connector}
              defaultedCredential={defaultedCredential}
              credentials={credentials}
              editableCredentials={editableCredentials}
              onDeleteCredential={onDeleteCredential}
              onEditCredential={(credential: Credential<any>) =>
                onEditCredential(credential)
              }
              onSwap={onSwap}
              onCreateNew={() => makeShowCreateCredential()}
            />
          </Modal.Content>
        </Modal>
      )}

      {editingCredential && (
        <Modal open onOpenChange={closeEditingCredential}>
          <Modal.Content>
            <Modal.Header
              icon={SvgEdit}
              title="Edit Credential"
              description="Ensure that you update to a credential with the proper permissions!"
              onClose={closeEditingCredential}
            />
            <EditCredential
              onUpdate={onUpdateCredential}
              credential={editingCredential}
              onClose={closeEditingCredential}
            />
          </Modal.Content>
        </Modal>
      )}

      {showCreateCredential && (
        <Modal open onOpenChange={closeCreateCredential}>
          <Modal.Content>
            <Modal.Header
              icon={SvgKey}
              title={`Create ${getSourceDisplayName(sourceType)} Credential`}
              onClose={closeCreateCredential}
            />
            <Modal.Body>
              {oauthDetailsLoading ? (
                <Spinner />
              ) : (
                <>
                  {oauthDetails && oauthDetails.oauth_enabled ? (
                    <CreateStdOAuthCredential
                      sourceType={sourceType}
                      additionalFields={oauthDetails.additional_kwargs}
                    />
                  ) : (
                    <CreateCredential
                      sourceType={sourceType}
                      accessType={ccPair.access_type}
                      swapConnector={ccPair.connector}
                      onSwap={onSwap}
                      onClose={closeCreateCredential}
                    />
                  )}
                </>
              )}
            </Modal.Body>
          </Modal.Content>
        </Modal>
      )}

      <Card padding={0.5}>
        <LineItemLayout
          icon={SvgKey}
          title={
            ccPair.credential.name || `Credential #${ccPair.credential.id}`
          }
          description={`Created ${new Date(
            ccPair.credential.time_created
          ).toLocaleDateString(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
          })}${
            ccPair.credential.user_email
              ? ` by ${ccPair.credential.user_email}`
              : ""
          }`}
          rightChildren={
            <Button
              icon={SvgEdit}
              prominence="tertiary"
              onClick={() => setShowModifyCredential(true)}
            />
          }
          reducedPadding
        />
      </Card>
    </>
  );
}
