"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, MessageCard, Modal, Text, useModal } from "@opal/components";
import { Section, toast } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgArrowExchange, SvgServer, SvgTrash } from "@opal/icons";
import { markdown } from "@opal/utils";
import { can } from "@/lib/permissions/resource-actions";
import type { MCPServer } from "@/lib/mcp/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import MCPServerDetailsPage from "@/sections/actions/modals/MCPServerDetailsPage";
import MCPAuthenticationPage from "@/sections/actions/modals/MCPAuthenticationPage";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import { UnsavedChangesModalContent } from "@/sections/modals/UnsavedChangesModal";

export type MCPSetupPage = "server" | "authentication";

interface MCPServerSetupModalProps {
  server: MCPServer | null;
  initialPage?: MCPSetupPage;
  onTriggerFetchTools?: (serverId: number) => Promise<void> | void;
  onServerSaved?: (server: MCPServer) => void;
  mutateMcpServers?: () => Promise<void>;
  onDelete?: () => Promise<void>;
  skipOverlay?: boolean;
  editOnly?: boolean;
  onCompleted?: (server: MCPServer) => void;
}

export default function MCPServerSetupModal(props: MCPServerSetupModalProps) {
  const { isOpen } = useModal();
  // Closing ends the editing session; moving between pages does not.
  return isOpen ? <MCPSetupSession {...props} /> : null;
}

function MCPSetupSession({
  server,
  initialPage = "server",
  onTriggerFetchTools,
  onServerSaved,
  mutateMcpServers,
  onDelete,
  skipOverlay = false,
  editOnly = false,
  onCompleted,
}: MCPServerSetupModalProps) {
  const t = useTranslations("actions");
  const { toggle } = useModal();
  const detailsPanel = useRef<HTMLDivElement>(null);
  const authPanel = useRef<HTMLDivElement>(null);
  const confirmationPanel = useRef<HTMLDivElement>(null);
  const [page, setPage] = useState<MCPSetupPage>(
    server ? initialPage : "server"
  );
  const [savedServer, setSavedServer] = useState<MCPServer | null>(null);
  const [loaded, setLoaded] = useState(!server);
  const [busy, setBusy] = useState(false);
  const [deleteRequested, setDeleteRequested] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [detailsDirty, setDetailsDirty] = useState(false);
  const [authDirty, setAuthDirty] = useState(false);
  const unsavedChanges = useUnsavedChangesGuard({
    isDirty: detailsDirty || authDirty,
  });
  const confirmationOpen = unsavedChanges.confirmationOpen || deleteRequested;
  const [footerTarget, setFooterTarget] = useState<HTMLDivElement | null>(null);
  const [visitedDetails, setVisitedDetails] = useState(page === "server");
  const [visitedAuth, setVisitedAuth] = useState(page === "authentication");
  const { error } = useSWR<MCPServer, Error>(
    server && !loaded ? SWR_KEYS.adminMcpServer(server.id) : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 0,
      onSuccess(freshServer) {
        setSavedServer(freshServer);
        setLoaded(true);
      },
    }
  );

  useEffect(() => {
    if (!loaded) return;
    if (confirmationOpen) {
      confirmationPanel.current
        ?.querySelector<HTMLButtonElement>("button")
        ?.focus();
      return;
    }
    const panel = page === "server" ? detailsPanel.current : authPanel.current;
    const field = panel?.querySelector<HTMLElement>(
      'input:not(:disabled), [role="tab"][aria-selected="true"]'
    );
    (field ?? panel)?.focus();
  }, [page, loaded, confirmationOpen]);

  const close = useCallback(() => {
    if (!busy && !deleting) unsavedChanges.requestLeave(() => toggle(false));
  }, [busy, deleting, toggle, unsavedChanges.requestLeave]);
  const showDetails = () => {
    if (busy) return;
    setVisitedDetails(true);
    setPage("server");
  };
  const refreshOverview = async () => {
    try {
      if (savedServer) {
        const fresh = await errorHandlingFetcher<MCPServer>(
          SWR_KEYS.adminMcpServer(savedServer.id)
        );
        setSavedServer(fresh);
        onServerSaved?.(fresh);
      }
      await mutateMcpServers?.();
    } catch (error) {
      console.error("Error refreshing MCP servers:", error);
    }
  };
  const deleteServer = async () => {
    if (!onDelete || deleting) return;
    setDeleting(true);
    try {
      await onDelete();
      toggle(false);
    } catch (error) {
      console.error("Error deleting MCP server:", error);
      toast.error(
        error instanceof Error
          ? error.message
          : t("mcpPage.toasts.deleteFailed")
      );
    } finally {
      setDeleting(false);
    }
  };
  const completeAuthentication = async () => {
    if (!savedServer) return;
    const freshServer = await errorHandlingFetcher<MCPServer>(
      SWR_KEYS.adminMcpServer(savedServer.id)
    );
    setSavedServer(freshServer);
    onServerSaved?.(freshServer);
    toggle(false);
    onCompleted?.(freshServer);
  };
  const handleSaved = async (nextServer: MCPServer, advance: boolean) => {
    // Credentials for the previous URL must not remain in the authentication draft.
    if (savedServer?.server_url !== nextServer.server_url)
      setVisitedAuth(false);
    setSavedServer(nextServer);
    onServerSaved?.(nextServer);
    if (editOnly) {
      toggle(false);
    } else if (advance) {
      const freshServer = await errorHandlingFetcher<MCPServer>(
        SWR_KEYS.adminMcpServer(nextServer.id)
      );
      setSavedServer(freshServer);
      setVisitedAuth(true);
      setPage("authentication");
    }
  };

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (open || deleting) return;
        if (deleteRequested) {
          setDeleteRequested(false);
          return;
        }
        if (unsavedChanges.confirmationOpen) unsavedChanges.cancelLeave();
        else close();
      }}
    >
      <Modal.Content
        width={confirmationOpen ? "sm" : "md"}
        height="fit"
        skipOverlay={skipOverlay}
        preventAccidentalClose={false}
      >
        <div
          hidden={confirmationOpen}
          className={confirmationOpen ? "hidden" : "contents"}
        >
          {!confirmationOpen && (
            <Modal.Header
              padding={4}
              icon={page === "server" ? SvgServer : SvgArrowExchange}
              title={
                page === "server"
                  ? t(
                      savedServer
                        ? "addMcpModal.manageHeader.title"
                        : "addMcpModal.addHeader.title"
                    )
                  : savedServer
                    ? markdown(
                        t("mcpAuthModal.header.title", {
                          name: savedServer.name,
                        })
                      )
                    : t("mcpAuthModal.header.defaultTitle")
              }
              description={
                page === "server"
                  ? t(
                      savedServer
                        ? "addMcpModal.manageHeader.description"
                        : "addMcpModal.addHeader.description"
                    )
                  : t("mcpAuthModal.header.description")
              }
              onClose={close}
            />
          )}
          <Modal.Body animateHeight padding={0} gap={0} alignItems="stretch">
            {!loaded ? (
              <Section padding={6}>
                {error ? (
                  <MessageCard
                    variant="error"
                    title={t("mcpAuthModal.errors.loadStage")}
                    description={error.message}
                  />
                ) : (
                  <IconLoader />
                )}
              </Section>
            ) : (
              <>
                {visitedDetails && (
                  <div
                    ref={detailsPanel}
                    tabIndex={-1}
                    aria-label={t("mcpSetup.serverDetails")}
                    hidden={page !== "server"}
                  >
                    <MCPServerDetailsPage
                      editOnly={editOnly}
                      active={page === "server"}
                      footerTarget={footerTarget}
                      server={savedServer}
                      onSaved={handleSaved}
                      onBusyChange={setBusy}
                      onDirtyChange={setDetailsDirty}
                      onClose={close}
                      onDelete={
                        savedServer && can(savedServer, "delete") && onDelete
                          ? () => setDeleteRequested(true)
                          : undefined
                      }
                      mutateMcpServers={mutateMcpServers}
                    />
                  </div>
                )}
                {visitedAuth && savedServer && (
                  <div
                    ref={authPanel}
                    tabIndex={-1}
                    aria-label={t("mcpSetup.authentication")}
                    hidden={page !== "authentication"}
                  >
                    <MCPAuthenticationPage
                      active={page === "authentication"}
                      footerTarget={footerTarget}
                      key={`${savedServer.id}:${savedServer.server_url}`}
                      mcpServer={savedServer}
                      onTriggerFetchTools={onTriggerFetchTools}
                      onBusyChange={setBusy}
                      onDirtyChange={setAuthDirty}
                      onBack={editOnly ? undefined : showDetails}
                      onCancel={close}
                      onSaved={refreshOverview}
                      onComplete={completeAuthentication}
                    />
                  </div>
                )}
              </>
            )}
          </Modal.Body>
          {/* Page footers keep Formik context and stay outside the scrolling body. */}
          <div ref={setFooterTarget} className="shrink-0" />
        </div>
        {deleteRequested && savedServer ? (
          <div ref={confirmationPanel} className="contents">
            <Modal.Header
              icon={SvgTrash}
              title={t("mcpCard.deleteModal.title")}
              onClose={() => {
                if (!deleting) setDeleteRequested(false);
              }}
            />
            <Modal.Body>
              <Text as="p" color="text-03">
                {t.markup("mcpCard.deleteModal.body.description", {
                  title: savedServer.name,
                  emphasis: (chunks) => chunks,
                })}
              </Text>
              <Text as="p" color="text-03">
                {t("mcpCard.deleteModal.body.confirmation")}
              </Text>
            </Modal.Body>
            <Modal.Footer>
              <Button
                prominence="secondary"
                disabled={deleting}
                onClick={() => setDeleteRequested(false)}
              >
                {t("addMcpModal.cancelButton.label")}
              </Button>
              <Button
                variant="danger"
                disabled={deleting}
                onClick={deleteServer}
              >
                {t("mcpCard.deleteModal.submitButton.label")}
              </Button>
            </Modal.Footer>
          </div>
        ) : (
          unsavedChanges.confirmationOpen && (
            <div ref={confirmationPanel} className="contents">
              <UnsavedChangesModalContent
                onCancel={unsavedChanges.cancelLeave}
                onDiscard={unsavedChanges.discardAndLeave}
              />
            </div>
          )
        )}
      </Modal.Content>
    </Modal>
  );
}
