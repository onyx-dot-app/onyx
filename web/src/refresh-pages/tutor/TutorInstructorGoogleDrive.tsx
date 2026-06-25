"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import useSWR from "swr";
import { Button } from "@opal/components";
import {
  SvgExternalLink,
  SvgFolderPlus,
  SvgRefreshCw,
  SvgTrash,
} from "@opal/icons";
import { ThreeDotsLoader } from "@/components/Loading";
import { CCPairStatus } from "@/components/Status";
import Title from "@/components/ui/title";
import { Card } from "@/components/ui/card";
import { Callout } from "@/components/ui/callout";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ValidStatuses } from "@/lib/types";
import { localizeAndPrettify, timeAgo } from "@/lib/time";
import { ConnectorCredentialPairStatus } from "@/app/admin/connector/[ccPairId]/types";

interface LtiGoogleDriveFolderSnapshot {
  id: string;
  url: string;
}

interface LtiCourseGoogleDriveSnapshot {
  oauth_app_configured: boolean;
  connected: boolean;
  credential_id: number | null;
  credential_name: string | null;
  credential_email: string | null;
  cc_pair_id: number | null;
  connector_id: number | null;
  cc_pair_status: ConnectorCredentialPairStatus | null;
  indexing_status: ValidStatuses | null;
  total_docs_indexed: number;
  has_indexed_documents: boolean;
  last_successful_index_time: string | null;
  folders: LtiGoogleDriveFolderSnapshot[];
}

interface LtiGoogleDriveConnectResponse {
  credential_id: number;
  auth_url: string;
}

interface TutorInstructorGoogleDriveProps {
  courseId: string;
}

function folderKey(folder: LtiGoogleDriveFolderSnapshot): string {
  return folder.id || folder.url;
}

function normalizeFolderInput(input: string): LtiGoogleDriveFolderSnapshot {
  const trimmedInput = input.trim();
  const urlMatch = trimmedInput.match(/\/folders\/([^/?#]+)/);
  const id = urlMatch?.[1] ?? trimmedInput;
  return {
    id,
    url: urlMatch
      ? trimmedInput
      : `https://drive.google.com/drive/folders/${id}`,
  };
}

function getErrorDetail(payload: unknown, fallback: string): string {
  if (
    payload &&
    typeof payload === "object" &&
    "detail" in payload &&
    typeof payload.detail === "string"
  ) {
    return payload.detail;
  }
  return fallback;
}

function KnowledgeMetricCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: ReactNode;
  detail?: string;
}) {
  return (
    <Card className="min-h-[132px] px-6 py-5">
      <div className="text-xs font-medium uppercase tracking-wide text-subtle">
        {label}
      </div>
      <div className="mt-3 text-2xl font-semibold text-text-default">
        {value}
      </div>
      {detail && <div className="mt-2 text-sm text-subtle">{detail}</div>}
    </Card>
  );
}

export default function TutorInstructorGoogleDrive({
  courseId,
}: TutorInstructorGoogleDriveProps) {
  const googleDriveKey = `/api/auth/lti/course/${encodeURIComponent(
    courseId
  )}/google-drive`;
  const popupPollRef = useRef<number | null>(null);

  const {
    data: googleDrive,
    isLoading,
    mutate,
  } = useSWR<LtiCourseGoogleDriveSnapshot>(
    googleDriveKey,
    errorHandlingFetcher,
    { refreshInterval: 10_000 }
  );

  const [folderInput, setFolderInput] = useState("");
  const [isConnecting, setIsConnecting] = useState(false);
  const [isUpdatingFolders, setIsUpdatingFolders] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);

  useEffect(() => {
    const handleOAuthMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) {
        return;
      }
      if (
        !event.data ||
        typeof event.data !== "object" ||
        event.data.type !== "onyx:lti-google-drive-oauth"
      ) {
        return;
      }

      void mutate();
      if (event.data.status === "success") {
        toast.success("Google Drive connected.");
      } else {
        toast.error("Could not finish Google Drive authorization.");
      }
    };

    window.addEventListener("message", handleOAuthMessage);
    return () => {
      window.removeEventListener("message", handleOAuthMessage);
      if (popupPollRef.current !== null) {
        window.clearInterval(popupPollRef.current);
      }
    };
  }, []);

  const handleConnect = useCallback(async () => {
    setIsConnecting(true);
    try {
      const response = await fetch(`${googleDriveKey}/connect`, {
        method: "POST",
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(
          getErrorDetail(payload, "Could not start Google Drive connection.")
        );
      }

      const payload = (await response.json()) as LtiGoogleDriveConnectResponse;
      const popup = window.open(
        payload.auth_url,
        "onyx-google-drive-oauth",
        "width=720,height=820"
      );
      if (!popup) {
        toast.error("Popup blocked. Allow popups and try again.");
        return;
      }

      toast.success("Google Drive authorization opened.");
      if (popupPollRef.current !== null) {
        window.clearInterval(popupPollRef.current);
      }
      popupPollRef.current = window.setInterval(() => {
        if (!popup.closed) return;
        if (popupPollRef.current !== null) {
          window.clearInterval(popupPollRef.current);
          popupPollRef.current = null;
        }
        void mutate();
      }, 1000);
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Could not connect Google Drive."
      );
    } finally {
      setIsConnecting(false);
    }
  }, [googleDriveKey, mutate]);

  const saveFolders = useCallback(
    async ({
      folders,
      successMessage,
      errorMessage,
    }: {
      folders: LtiGoogleDriveFolderSnapshot[];
      successMessage: string;
      errorMessage: string;
    }) => {
      if (folders.length === 0) {
        toast.error("Add at least one folder.");
        return false;
      }

      setIsUpdatingFolders(true);
      try {
        const response = await fetch(googleDriveKey, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            folders: folders.map((folder) => ({ url: folder.url })),
          }),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(getErrorDetail(payload, errorMessage));
        }

        toast.success(successMessage);
        await mutate();
        return true;
      } catch (e) {
        toast.error(e instanceof Error ? e.message : errorMessage);
        return false;
      } finally {
        setIsUpdatingFolders(false);
      }
    },
    [googleDriveKey, mutate]
  );

  const handleAddFolder = useCallback(async () => {
    const trimmedInput = folderInput.trim();
    if (!trimmedInput) {
      toast.error("Enter a Google Drive folder URL or ID.");
      return;
    }

    const folder = normalizeFolderInput(trimmedInput);
    const nextFolders = [
      ...(googleDrive?.folders ?? []).filter(
        (currentFolder) => folderKey(currentFolder) !== folderKey(folder)
      ),
      folder,
    ];
    const saved = await saveFolders({
      folders: nextFolders,
      successMessage: "Google Drive folder added. Indexing has started.",
      errorMessage: "Could not add Google Drive folder.",
    });
    if (saved) {
      setFolderInput("");
    }
  }, [folderInput, googleDrive?.folders, saveFolders]);

  const handleSync = useCallback(async () => {
    setIsSyncing(true);
    try {
      const response = await fetch(`${googleDriveKey}/sync`, {
        method: "POST",
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(
          getErrorDetail(payload, "Could not sync Google Drive folders.")
        );
      }

      toast.success("Google Drive sync started.");
      await mutate();
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Could not sync Google Drive folders."
      );
    } finally {
      setIsSyncing(false);
    }
  }, [googleDriveKey, mutate]);

  const handleDisconnect = useCallback(async () => {
    setIsDisconnecting(true);
    try {
      const response = await fetch(googleDriveKey, {
        method: "DELETE",
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(
          getErrorDetail(payload, "Could not disconnect Google Drive.")
        );
      }

      toast.success("Google Drive disconnected for this course.");
      await mutate();
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Could not disconnect Google Drive."
      );
    } finally {
      setIsDisconnecting(false);
    }
  }, [googleDriveKey, mutate]);

  const removeFolder = useCallback(
    async (folderId: string) => {
      const currentFolders = googleDrive?.folders ?? [];
      const nextFolders = currentFolders.filter(
        (folder) => folderKey(folder) !== folderId
      );
      if (nextFolders.length === currentFolders.length) {
        return;
      }
      if (nextFolders.length === 0) {
        toast.error("Disconnect Drive to remove the last folder.");
        return;
      }

      await saveFolders({
        folders: nextFolders,
        successMessage: "Google Drive folder removed. Indexing has started.",
        errorMessage: "Could not remove Google Drive folder.",
      });
    },
    [googleDrive?.folders, saveFolders]
  );

  return (
    <div className="mt-8">
      <div className="mb-2 flex items-center justify-between gap-4">
        <Title size="md">Google Drive</Title>
        {googleDrive?.connected ? (
          <Button
            prominence="secondary"
            icon={SvgRefreshCw}
            disabled={!googleDrive.cc_pair_id || isSyncing}
            onClick={() => void handleSync()}
          >
            Sync Drive
          </Button>
        ) : null}
      </div>

      {isLoading ? (
        <div className="flex w-full items-center justify-center py-8">
          <ThreeDotsLoader />
        </div>
      ) : !googleDrive ? (
        <Callout type="warning" title="Google Drive unavailable">
          Could not load Google Drive status for this course.
        </Callout>
      ) : (
        <>
          {!googleDrive.connected && !googleDrive.oauth_app_configured ? (
            <Callout type="warning" title="Google Drive OAuth is not set up">
              Ask an admin to upload a Google Drive OAuth app JSON before
              connecting course folders.
            </Callout>
          ) : !googleDrive.connected ? (
            <Card className="p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <Title size="sm">Connect Google Drive</Title>
                  <Text as="p" secondaryBody text03 className="mt-1">
                    Authorize a Google account before adding folders.
                  </Text>
                </div>
                <Button
                  icon={SvgExternalLink}
                  disabled={isConnecting}
                  onClick={() => void handleConnect()}
                >
                  Connect
                </Button>
              </div>
            </Card>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                <KnowledgeMetricCard
                  label="Documents Synced"
                  value={googleDrive.total_docs_indexed.toLocaleString()}
                  detail={
                    googleDrive.has_indexed_documents
                      ? "Available for tutor retrieval"
                      : "No Drive documents indexed yet"
                  }
                />

                <KnowledgeMetricCard
                  label="Last Synced"
                  value={
                    timeAgo(googleDrive.last_successful_index_time) ?? "Never"
                  }
                  detail={
                    googleDrive.last_successful_index_time
                      ? localizeAndPrettify(
                          googleDrive.last_successful_index_time
                        )
                      : "No sync has run yet"
                  }
                />

                <KnowledgeMetricCard
                  label="Status"
                  value={
                    googleDrive.cc_pair_status ? (
                      <CCPairStatus
                        ccPairStatus={googleDrive.cc_pair_status}
                        inRepeatedErrorState={false}
                        lastIndexAttemptStatus={googleDrive.indexing_status}
                      />
                    ) : (
                      "Connected"
                    )
                  }
                  detail={
                    googleDrive.credential_email ??
                    googleDrive.credential_name ??
                    "Google Drive account connected"
                  }
                />
              </div>

              <Card className="mt-4 p-4">
                <form
                  className="flex flex-col gap-3 sm:flex-row sm:items-center"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void handleAddFolder();
                  }}
                >
                  <div className="flex-1">
                    <InputTypeIn
                      value={folderInput}
                      onChange={(e) => setFolderInput(e.target.value)}
                      placeholder="https://drive.google.com/drive/folders/..."
                      autoComplete="off"
                      showClearButton={false}
                    />
                  </div>
                  <Button
                    type="submit"
                    icon={SvgFolderPlus}
                    disabled={isUpdatingFolders}
                  >
                    Add Folder
                  </Button>
                </form>
              </Card>

              <div className="mt-4">
                {googleDrive.folders.length === 0 ? (
                  <Callout type="notice" title="No Drive folders selected">
                    Add a folder above to give the tutor Drive knowledge for
                    this course.
                  </Callout>
                ) : (
                  <Card className="overflow-hidden p-0">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Folder</TableHead>
                          <TableHead />
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {googleDrive.folders.map((folder) => (
                          <TableRow
                            key={folderKey(folder)}
                            className="border-border"
                          >
                            <TableCell className="max-w-[28rem] truncate">
                              {folder.url}
                            </TableCell>
                            <TableCell>
                              <Button
                                prominence="tertiary"
                                variant="danger"
                                size="sm"
                                icon={SvgTrash}
                                disabled={isUpdatingFolders}
                                onClick={() =>
                                  void removeFolder(folderKey(folder))
                                }
                              />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </Card>
                )}
              </div>

              {googleDrive.cc_pair_id && (
                <div className="mt-4 flex justify-end">
                  <Button
                    prominence="tertiary"
                    variant="danger"
                    disabled={isDisconnecting}
                    onClick={() => void handleDisconnect()}
                  >
                    Disconnect Drive
                  </Button>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
