import { toast } from "@/hooks/useToast";
import React, { useState, useEffect } from "react";
import { useSWRConfig } from "swr";
import * as Yup from "yup";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { adminDeleteCredential } from "@/lib/credential";
import { setupGoogleDriveOAuth } from "@/lib/googleDrive";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { TextFormField, SectionHeader } from "@/components/Field";
import { Form, Formik } from "formik";
import { User } from "@/lib/types";
import { Button } from "@opal/components";
import {
  Credential,
  GoogleDriveCredentialJson,
  GoogleDriveServiceAccountCredentialJson,
} from "@/lib/connectors/credentials";
import { refreshAllGoogleData } from "@/lib/googleConnector";
import { ValidSources } from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";
import { FiFile, FiCheck, FiLink, FiAlertTriangle } from "react-icons/fi";
import { truncateString } from "@/lib/utils";
import { cn } from "@opal/utils";

type GoogleDriveCredentialJsonTypes = "authorized_user" | "service_account";

export const DriveJsonUpload = ({ onSuccess }: { onSuccess?: () => void }) => {
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

      // Check credential type
      let credentialFileType: GoogleDriveCredentialJsonTypes;
      try {
        const appCredentialJson = JSON.parse(credentialJsonStr);
        if (appCredentialJson.web) {
          credentialFileType = "authorized_user";
        } else if (appCredentialJson.type === "service_account") {
          credentialFileType = "service_account";
        } else {
          throw new Error(
            "未知凭据类型，应为“OAuth Web application”或“Service Account”之一"
          );
        }
      } catch (e) {
        toast.error(`提供的文件无效 - ${e}`);
        setIsUploading(false);
        return;
      }

      if (credentialFileType === "authorized_user") {
        const response = await fetch(
          "/api/manage/admin/connector/google-drive/app-credential",
          {
            method: "PUT",
            headers: {
              "Content-Type": "application/json",
            },
            body: credentialJsonStr,
          }
        );
        if (response.ok) {
          toast.success("应用凭据上传成功");
          mutate(SWR_KEYS.googleConnectorAppCredential("google-drive"));
          if (onSuccess) {
            onSuccess();
          }
        } else {
          const errorMsg = await response.text();
          toast.error(`应用凭据上传失败 - ${errorMsg}`);
        }
      }

      if (credentialFileType === "service_account") {
        const response = await fetch(
          "/api/manage/admin/connector/google-drive/service-account-key",
          {
            method: "PUT",
            headers: {
              "Content-Type": "application/json",
            },
            body: credentialJsonStr,
          }
        );
        if (response.ok) {
          toast.success("Service Account Key 上传成功");
          mutate(SWR_KEYS.googleConnectorServiceAccountKey("google-drive"));
          if (onSuccess) {
            onSuccess();
          }
        } else {
          const errorMsg = await response.text();
          toast.error(`Service Account Key 上传失败 - ${errorMsg}`);
        }
      }
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
        toast.error("请上传 JSON 文件");
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
                  ? `正在上传 ${truncateString(fileName || "文件", 50)}...`
                  : isDragging
                    ? "将 JSON 文件拖到此处"
                    : truncateString(
                        fileName || "选择或拖入 JSON 凭据文件...",
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

interface DriveJsonUploadSectionProps {
  appCredentialData?: { client_id: string };
  serviceAccountCredentialData?: { service_account_email: string };
  isAdmin: boolean;
  onSuccess?: () => void;
  existingAuthCredential?: boolean;
}

export const DriveJsonUploadSection = ({
  appCredentialData,
  serviceAccountCredentialData,
  isAdmin,
  onSuccess,
  existingAuthCredential,
}: DriveJsonUploadSectionProps) => {
  const { mutate } = useSWRConfig();
  const router = useRouter();
  const [localServiceAccountData, setLocalServiceAccountData] = useState(
    serviceAccountCredentialData
  );
  const [localAppCredentialData, setLocalAppCredentialData] =
    useState(appCredentialData);

  // Update local state when props change
  useEffect(() => {
    setLocalServiceAccountData(serviceAccountCredentialData);
    setLocalAppCredentialData(appCredentialData);
  }, [serviceAccountCredentialData, appCredentialData]);

  const handleSuccess = () => {
    if (onSuccess) {
      onSuccess();
    } else {
      refreshAllGoogleData(ValidSources.GoogleDrive);
    }
  };

  if (!isAdmin) {
    return (
      <div>
        <div className="flex items-start py-3 px-4 bg-yellow-50/30 dark:bg-yellow-900/5 rounded-sm">
          <FiAlertTriangle className="text-yellow-500 h-5 w-5 mr-2 mt-0.5 shrink-0" />
          <p className="text-sm">
            策展者无法设置 Google Drive 凭据。若要添加 Google Drive 连接器，请联系管理员。
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <p className="text-sm mb-3">
        要连接 Google Drive，请创建凭据（OAuth App 或 Service Account），下载 JSON 文件并在下方上传。
      </p>
      <div className="mb-4">
        <a
          className="text-primary hover:text-primary/80 flex items-center gap-1 text-sm"
          target="_blank"
          href={`${DOCS_ADMINS_PATH}/connectors/official/google_drive/overview`}
          rel="noreferrer"
        >
          <FiLink className="h-3 w-3" />
          查看详细设置说明
        </a>
      </div>

      {(localServiceAccountData?.service_account_email ||
        localAppCredentialData?.client_id) && (
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
                    localServiceAccountData?.service_account_email ||
                      localAppCredentialData?.client_id ||
                      "",
                    50
                  )}
                </span>
              </div>
            </label>
          </div>
          {isAdmin && !existingAuthCredential && (
            <div className="mt-2">
              <Button
                variant="danger"
                onClick={async () => {
                  const endpoint =
                    localServiceAccountData?.service_account_email
                      ? SWR_KEYS.googleConnectorServiceAccountKey(
                          "google-drive"
                        )
                      : SWR_KEYS.googleConnectorAppCredential("google-drive");

                  const response = await fetch(endpoint, {
                    method: "DELETE",
                  });

                  if (response.ok) {
                    mutate(endpoint);
                    // Also mutate the credential endpoints to ensure Step 2 is reset
                    mutate(
                      buildSimilarCredentialInfoURL(ValidSources.GoogleDrive)
                    );

                    // Add additional mutations to refresh all credential-related endpoints
                    mutate(SWR_KEYS.googleConnectorCredentials("google-drive"));
                    mutate(
                      SWR_KEYS.googleConnectorPublicCredential("google-drive")
                    );
                    mutate(
                      SWR_KEYS.googleConnectorServiceAccountCredential(
                        "google-drive"
                      )
                    );

                    toast.success(
                      `已删除 ${
                        localServiceAccountData
                        ? "Service Account Key"
                          : "应用凭据"
                      }`
                    );
                    // Immediately update local state
                    if (localServiceAccountData) {
                      setLocalServiceAccountData(undefined);
                    } else {
                      setLocalAppCredentialData(undefined);
                    }
                    handleSuccess();
                  } else {
                    const errorMsg = await response.text();
                    toast.error(`删除凭据失败 - ${errorMsg}`);
                  }
                }}
              >
                删除凭据
              </Button>
            </div>
          )}
        </div>
      )}

      {!(
        localServiceAccountData?.service_account_email ||
        localAppCredentialData?.client_id
      ) && <DriveJsonUpload onSuccess={handleSuccess} />}
    </div>
  );
};

interface DriveCredentialSectionProps {
  googleDrivePublicUploadedCredential?: Credential<GoogleDriveCredentialJson>;
  googleDriveServiceAccountCredential?: Credential<GoogleDriveServiceAccountCredentialJson>;
  serviceAccountKeyData?: { service_account_email: string };
  appCredentialData?: { client_id: string };
  refreshCredentials: () => void;
  connectorAssociated: boolean;
  user: User | null;
}

async function handleRevokeAccess(
  connectorAssociated: boolean,
  existingCredential:
    | Credential<GoogleDriveCredentialJson>
    | Credential<GoogleDriveServiceAccountCredentialJson>,
  refreshCredentials: () => void
) {
  if (connectorAssociated) {
    const message =
      "仍有连接器关联到此 Google Drive 凭据，无法撤销该凭据。请删除所有关联连接器后重试。";
    toast.error(message);
    return;
  }

  await adminDeleteCredential(existingCredential.id);
  toast.success("Google Drive 凭据已撤销！");

  refreshCredentials();
}

export const DriveAuthSection = ({
  googleDrivePublicUploadedCredential,
  googleDriveServiceAccountCredential,
  serviceAccountKeyData,
  appCredentialData,
  refreshCredentials,
  connectorAssociated,
  user,
}: DriveCredentialSectionProps) => {
  const router = useRouter();
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [localServiceAccountData, setLocalServiceAccountData] = useState(
    serviceAccountKeyData
  );
  const [localAppCredentialData, setLocalAppCredentialData] =
    useState(appCredentialData);
  const [
    localGoogleDrivePublicCredential,
    setLocalGoogleDrivePublicCredential,
  ] = useState(googleDrivePublicUploadedCredential);
  const [
    localGoogleDriveServiceAccountCredential,
    setLocalGoogleDriveServiceAccountCredential,
  ] = useState(googleDriveServiceAccountCredential);

  // Update local state when props change
  useEffect(() => {
    setLocalServiceAccountData(serviceAccountKeyData);
    setLocalAppCredentialData(appCredentialData);
    setLocalGoogleDrivePublicCredential(googleDrivePublicUploadedCredential);
    setLocalGoogleDriveServiceAccountCredential(
      googleDriveServiceAccountCredential
    );
  }, [
    serviceAccountKeyData,
    appCredentialData,
    googleDrivePublicUploadedCredential,
    googleDriveServiceAccountCredential,
  ]);

  const existingCredential =
    localGoogleDrivePublicCredential ||
    localGoogleDriveServiceAccountCredential;
  if (existingCredential) {
    return (
      <div>
        <div className="mt-4">
          <div className="py-3 px-4 bg-blue-50/30 dark:bg-blue-900/5 rounded-sm mb-4 flex items-start">
            <FiCheck className="text-blue-500 h-5 w-5 mr-2 mt-0.5 shrink-0" />
            <div className="flex-1">
              <span className="font-medium block">认证完成</span>
              <p className="text-sm mt-1 text-text-500 dark:text-text-400 wrap-break-word">
                Google Drive 凭据已成功上传并完成认证。
              </p>
            </div>
          </div>
          <Button
            variant="danger"
            onClick={async () => {
              handleRevokeAccess(
                connectorAssociated,
                existingCredential,
                refreshCredentials
              );
            }}
          >
            撤销访问
          </Button>
        </div>
      </div>
    );
  }

  // If no credentials are uploaded, show message to complete step 1 first
  if (
    !localServiceAccountData?.service_account_email &&
    !localAppCredentialData?.client_id
  ) {
    return (
      <div>
        <SectionHeader>Google Drive 认证</SectionHeader>
        <div className="mt-4">
          <div className="flex items-start py-3 px-4 bg-yellow-50/30 dark:bg-yellow-900/5 rounded-sm">
            <FiAlertTriangle className="text-yellow-500 h-5 w-5 mr-2 mt-0.5 shrink-0" />
            <p className="text-sm">
              请先完成步骤 1，上传 OAuth 凭据或 Service Account Key，然后继续认证。
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (localServiceAccountData?.service_account_email) {
    return (
      <div>
        <div className="mt-4">
          <Formik
            initialValues={{
              google_primary_admin: user?.email || "",
            }}
            validationSchema={Yup.object().shape({
              google_primary_admin: Yup.string()
                .email("请输入有效邮箱")
                .required("必填"),
            })}
            onSubmit={async (values, formikHelpers) => {
              formikHelpers.setSubmitting(true);
              try {
                const response = await fetch(
                  "/api/manage/admin/connector/google-drive/service-account-credential",
                  {
                    method: "PUT",
                    headers: {
                      "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                      google_primary_admin: values.google_primary_admin,
                    }),
                  }
                );

                if (response.ok) {
                  toast.success(
                    "Service Account 凭据创建成功"
                  );
                  refreshCredentials();
                } else {
                  const errorMsg = await response.text();
                  toast.error(
                    `创建 Service Account 凭据失败 - ${errorMsg}`
                  );
                }
              } catch (error) {
                toast.error(
                  `创建 Service Account 凭据失败 - ${error}`
                );
              } finally {
                formikHelpers.setSubmitting(false);
              }
            }}
          >
            {({ isSubmitting }) => (
              <Form>
                <TextFormField
                  name="google_primary_admin"
                  label="主管理员邮箱："
                  subtext="输入拥有目标 Google Drive 的 Google 组织管理员或所有者邮箱。"
                />
                <div className="flex">
                  <Button disabled={isSubmitting} type="submit">
                    {isSubmitting ? "正在创建..." : "创建凭据"}
                  </Button>
                </div>
              </Form>
            )}
          </Formik>
        </div>
      </div>
    );
  }

  if (localAppCredentialData?.client_id) {
    return (
      <div>
        <div className="bg-background-50/30 dark:bg-background-900/20 rounded-sm mb-4">
          <p className="text-sm">
            接下来，你需要通过 OAuth 认证 Google Drive。这会授予我们读取你 Google Drive 账号中可访问文档的权限。
          </p>
        </div>
        <Button
          disabled={isAuthenticating}
          onClick={async () => {
            setIsAuthenticating(true);
            try {
              const [authUrl, errorMsg] = await setupGoogleDriveOAuth({
                isAdmin: true,
                name: "OAuth (uploaded)",
              });

              if (authUrl) {
                router.push(authUrl as Route);
              } else {
                toast.error(errorMsg);
                setIsAuthenticating(false);
              }
            } catch (error) {
              toast.error(
                `Google Drive 认证失败 - ${error}`
              );
              setIsAuthenticating(false);
            }
          }}
        >
          {isAuthenticating
            ? "正在认证..."
            : "使用 Google Drive 认证"}
        </Button>
      </div>
    );
  }

  // This code path should not be reached with the new conditions above
  return null;
};
