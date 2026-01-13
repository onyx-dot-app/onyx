"use client";

import { PopupSpec } from "@/components/admin/connectors/Popup";
import React, { useState, useEffect } from "react";
import { useSWRConfig } from "swr";
import * as Yup from "yup";
import { TextFormField, SectionHeader } from "@/components/Field";
import { Form, Formik } from "formik";
import { User, ValidSources } from "@/lib/types";
import Button from "@/refresh-components/buttons/Button";
import { Credential, BoxCredentialJson } from "@/lib/connectors/credentials";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";
import { FiFile, FiCheck, FiLink, FiAlertTriangle } from "react-icons/fi";
import { cn, truncateString } from "@/lib/utils";
import { adminDeleteCredential } from "@/lib/credential";
import { DOCS_ADMINS_PATH } from "@/lib/constants";

export const BoxJsonUpload = ({
  setPopup,
  onSuccess,
}: {
  setPopup: (popupSpec: PopupSpec | null) => void;
  onSuccess?: () => void;
}) => {
  const { mutate } = useSWRConfig();
  const [isUploading, setIsUploading] = useState(false);
  const [fileName, setFileName] = useState<string | undefined>();
  const [isDragging, setIsDragging] = useState(false);

  const handleFileUpload = async (file: File) => {
    setIsUploading(true);
    setFileName(file.name);

    const reader = new FileReader();
    reader.onload = async (loadEvent) => {
      if (!loadEvent?.target?.result) {
        setIsUploading(false);
        return;
      }

      const credentialJsonStr = loadEvent.target.result as string;

      // Validate Box JWT config structure
      try {
        const jwtConfigJson = JSON.parse(credentialJsonStr);
        if (!jwtConfigJson.boxAppSettings) {
          throw new Error(
            "Invalid Box JWT config: missing 'boxAppSettings' field"
          );
        }
        if (!jwtConfigJson.boxAppSettings.clientID) {
          throw new Error(
            "Invalid Box JWT config: missing 'boxAppSettings.clientID'"
          );
        }
        if (!jwtConfigJson.boxAppSettings.appAuth) {
          throw new Error(
            "Invalid Box JWT config: missing 'boxAppSettings.appAuth'"
          );
        }
      } catch (e) {
        setPopup({
          message: `Invalid Box JWT config file - ${e}`,
          type: "error",
        });
        setIsUploading(false);
        return;
      }

      try {
        const response = await fetch(
          "/api/manage/admin/connector/box/jwt-config",
          {
            method: "PUT",
            headers: {
              "Content-Type": "application/json",
            },
            body: credentialJsonStr,
          }
        );
        if (response.ok) {
          setPopup({
            message: "Successfully uploaded Box JWT config",
            type: "success",
          });
          mutate("/api/manage/admin/connector/box/jwt-config");
          if (onSuccess) {
            onSuccess();
          }
        } else {
          const errorMsg = await response.text();
          setPopup({
            message: `Failed to upload Box JWT config - ${errorMsg}`,
            type: "error",
          });
        }
      } catch (error) {
        setPopup({
          message: `Failed to upload Box JWT config - ${error}`,
          type: "error",
        });
      } finally {
        setIsUploading(false);
      }
    };

    reader.onerror = () => {
      setPopup({
        message: "Failed to read file. Please try again.",
        type: "error",
      });
      setIsUploading(false);
    };

    reader.onabort = () => {
      setPopup({
        message: "File read was aborted. Please try again.",
        type: "error",
      });
      setIsUploading(false);
    };

    reader.readAsText(file);
  };

  const handleDragEnter = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isUploading) {
      setIsDragging(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDragOver = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    if (isUploading) return;

    const files = e.dataTransfer.files;
    if (files.length > 0) {
      const file = files[0];
      if (
        file !== undefined &&
        (file.type === "application/json" || file.name.endsWith(".json"))
      ) {
        handleFileUpload(file);
      } else {
        setPopup({
          message: "Please upload a JSON file",
          type: "error",
        });
      }
    }
  };

  return (
    <div className="flex flex-col mt-4">
      <div className="flex items-center">
        <div className="relative flex flex-1 items-center">
          <label
            className={cn(
              "flex h-10 items-center justify-center w-full px-4 py-2 border border-dashed rounded-md transition-colors",
              isUploading
                ? "opacity-70 cursor-not-allowed border-background-400 bg-background-50/30"
                : isDragging
                  ? "bg-background-50/50 border-primary dark:border-primary"
                  : "cursor-pointer hover:bg-background-50/30 hover:border-primary dark:hover:border-primary border-background-300 dark:border-background-600"
            )}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
          >
            <div className="flex items-center space-x-2">
              {isUploading ? (
                <div className="h-4 w-4 border-t-2 border-b-2 border-primary rounded-full animate-spin"></div>
              ) : (
                <FiFile className="h-4 w-4 text-text-500" />
              )}
              <span className="text-sm text-text-500">
                {isUploading
                  ? `Uploading ${truncateString(fileName || "file", 50)}...`
                  : isDragging
                    ? "Drop JSON file here"
                    : truncateString(
                        fileName || "Select or drag Box JWT config file...",
                        50
                      )}
              </span>
            </div>
            <input
              className="sr-only"
              type="file"
              accept=".json"
              disabled={isUploading}
              onChange={(event) => {
                if (!event.target.files?.length) {
                  return;
                }
                const file = event.target.files[0];
                if (file === undefined) {
                  return;
                }
                handleFileUpload(file);
              }}
            />
          </label>
        </div>
      </div>
    </div>
  );
};

interface BoxJsonUploadSectionProps {
  setPopup: (popupSpec: PopupSpec | null) => void;
  jwtConfigData?: { client_id: string; enterprise_id: string };
  isAdmin: boolean;
  onSuccess?: () => void;
  existingAuthCredential?: boolean;
}

export const BoxJsonUploadSection = ({
  setPopup,
  jwtConfigData,
  isAdmin,
  onSuccess,
  existingAuthCredential,
}: BoxJsonUploadSectionProps) => {
  const { mutate } = useSWRConfig();
  const [localJwtConfigData, setLocalJwtConfigData] = useState(jwtConfigData);

  // Update local state when props change
  useEffect(() => {
    setLocalJwtConfigData(jwtConfigData);
  }, [jwtConfigData]);

  const handleSuccess = () => {
    if (onSuccess) {
      onSuccess();
    }
  };

  if (!isAdmin) {
    return (
      <div>
        <div className="flex items-start py-3 px-4 bg-yellow-50/30 dark:bg-yellow-900/5 rounded">
          <FiAlertTriangle className="text-yellow-500 h-5 w-5 mr-2 mt-0.5 flex-shrink-0" />
          <p className="text-sm">
            Curators are unable to set up the Box credentials. To add a Box
            connector, please contact an administrator.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <p className="text-sm mb-3">
        To connect your Box account, create a Box Platform App with JWT
        authentication, download the JSON config file, and upload it below.
      </p>
      <div className="mb-4">
        <a
          className="text-primary hover:text-primary/80 flex items-center gap-1 text-sm"
          target="_blank"
          href={`${DOCS_ADMINS_PATH}/connectors/official/box/overview`}
          rel="noreferrer"
        >
          <FiLink className="h-3 w-3" />
          View detailed setup instructions
        </a>
      </div>

      {localJwtConfigData?.client_id && (
        <div className="mb-4">
          <div className="relative flex flex-1 items-center">
            <label
              className={cn(
                "flex h-10 items-center justify-center w-full px-4 py-2 border border-dashed rounded-md transition-colors",
                "cursor-pointer hover:bg-background-50/30 hover:border-primary dark:hover:border-primary border-background-300 dark:border-background-600"
              )}
            >
              <div className="flex items-center space-x-2">
                <FiFile className="h-4 w-4 text-text-500" />
                <span className="text-sm text-text-500">
                  {truncateString(
                    `Client ID: ${localJwtConfigData.client_id}`,
                    50
                  )}
                </span>
              </div>
            </label>
          </div>
          {isAdmin && !existingAuthCredential && (
            <div className="mt-2">
              <Button
                danger
                onClick={async () => {
                  try {
                    const response = await fetch(
                      "/api/manage/admin/connector/box/jwt-config",
                      {
                        method: "DELETE",
                      }
                    );

                    if (response.ok) {
                      mutate("/api/manage/admin/connector/box/jwt-config");
                      mutate(buildSimilarCredentialInfoURL(ValidSources.Box));

                      setPopup({
                        message: "Successfully deleted Box JWT config",
                        type: "success",
                      });
                      setLocalJwtConfigData(undefined);
                      handleSuccess();
                    } else {
                      const errorMsg = await response.text();
                      setPopup({
                        message: `Failed to delete JWT config - ${errorMsg}`,
                        type: "error",
                      });
                    }
                  } catch (error) {
                    setPopup({
                      message: `Failed to delete JWT config - ${error}`,
                      type: "error",
                    });
                  }
                }}
              >
                Delete JWT Config
              </Button>
            </div>
          )}
        </div>
      )}

      {!localJwtConfigData?.client_id && (
        <BoxJsonUpload setPopup={setPopup} onSuccess={handleSuccess} />
      )}
    </div>
  );
};

interface BoxCredentialSectionProps {
  boxJwtCredential?: Credential<BoxCredentialJson>;
  jwtConfigData?: { client_id: string; enterprise_id: string };
  setPopup: (popupSpec: PopupSpec | null) => void;
  refreshCredentials: () => void;
  connectorAssociated: boolean;
  user: User | null;
}

async function handleRevokeAccess(
  connectorAssociated: boolean,
  setPopup: (popupSpec: PopupSpec | null) => void,
  existingCredential: Credential<BoxCredentialJson>,
  refreshCredentials: () => void
) {
  if (connectorAssociated) {
    const message =
      "Cannot revoke the Box credential while any connector is still associated with the credential. " +
      "Please delete all associated connectors, then try again.";
    setPopup({
      message: message,
      type: "error",
    });
    return;
  }

  const response = await adminDeleteCredential(existingCredential.id);
  if (response.ok) {
    setPopup({
      message: "Successfully revoked the Box credential!",
      type: "success",
    });
    refreshCredentials();
  } else {
    const errorMsg = await response.text();
    setPopup({
      message: `Failed to revoke Box credential - ${errorMsg}`,
      type: "error",
    });
  }
}

export const BoxAuthSection = ({
  boxJwtCredential,
  jwtConfigData,
  setPopup,
  refreshCredentials,
  connectorAssociated,
  user,
}: BoxCredentialSectionProps) => {
  const [localJwtConfigData, setLocalJwtConfigData] = useState(jwtConfigData);
  const [localBoxJwtCredential, setLocalBoxJwtCredential] =
    useState(boxJwtCredential);

  // Update local state when props change
  useEffect(() => {
    setLocalJwtConfigData(jwtConfigData);
    setLocalBoxJwtCredential(boxJwtCredential);
  }, [jwtConfigData, boxJwtCredential]);

  if (localBoxJwtCredential) {
    return (
      <div>
        <div className="mt-4">
          <div className="py-3 px-4 bg-blue-50/30 dark:bg-blue-900/5 rounded mb-4 flex items-start">
            <FiCheck className="text-blue-500 h-5 w-5 mr-2 mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <span className="font-medium block">Authentication Complete</span>
              <p className="text-sm mt-1 text-text-500 dark:text-text-400 break-words">
                Your Box JWT credentials have been successfully uploaded and
                authenticated.
              </p>
            </div>
          </div>
          <Button
            danger
            onClick={async () => {
              handleRevokeAccess(
                connectorAssociated,
                setPopup,
                localBoxJwtCredential,
                refreshCredentials
              );
            }}
          >
            Revoke Access
          </Button>
        </div>
      </div>
    );
  }

  // If no JWT config is uploaded, show message to complete step 1 first
  if (!localJwtConfigData?.client_id) {
    return (
      <div>
        <SectionHeader>Box Authentication</SectionHeader>
        <div className="mt-4">
          <div className="flex items-start py-3 px-4 bg-yellow-50/30 dark:bg-yellow-900/5 rounded">
            <FiAlertTriangle className="text-yellow-500 h-5 w-5 mr-2 mt-0.5 flex-shrink-0" />
            <p className="text-sm">
              Please complete Step 1 by uploading the Box JWT config file before
              proceeding with authentication.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // If JWT config is uploaded, show form to create credential with user ID
  return (
    <div>
      <div className="mt-4">
        <Formik
          initialValues={{
            box_primary_admin_user_id: "",
          }}
          validationSchema={Yup.object().shape({
            box_primary_admin_user_id: Yup.string().required(
              "Primary admin user ID is required"
            ),
          })}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);
            try {
              const response = await fetch(
                "/api/manage/admin/connector/box/jwt-credential",
                {
                  method: "PUT",
                  headers: {
                    "Content-Type": "application/json",
                  },
                  body: JSON.stringify({
                    box_primary_admin_user_id: values.box_primary_admin_user_id,
                  }),
                }
              );

              if (response.ok) {
                setPopup({
                  message: "Successfully created Box JWT credential",
                  type: "success",
                });
                refreshCredentials();
              } else {
                const errorMsg = await response.text();
                setPopup({
                  message: `Failed to create Box JWT credential - ${errorMsg}`,
                  type: "error",
                });
              }
            } catch (error) {
              setPopup({
                message: `Failed to create Box JWT credential - ${error}`,
                type: "error",
              });
            } finally {
              formikHelpers.setSubmitting(false);
            }
          }}
        >
          {({ isSubmitting }) => (
            <Form>
              <TextFormField
                name="box_primary_admin_user_id"
                label="Primary Admin User ID:"
                subtext="Enter the Box user ID of an admin/owner that has access to the Box content you want to index. You can find this in the Box Admin Console or by calling the Box API."
              />
              <div className="flex">
                <Button type="submit" disabled={isSubmitting}>
                  {isSubmitting ? "Creating..." : "Create Credential"}
                </Button>
              </div>
            </Form>
          )}
        </Formik>
      </div>
    </div>
  );
};
