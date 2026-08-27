"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useFocusOnMount } from "@opal/hooks";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { Modal } from "@opal/components";
import { InputVertical, toast } from "@opal/layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import { createMCPServer, updateMCPServer } from "@/lib/tools/svc";
import {
  MCPServerCreateRequest,
  MCPServerStatus,
  MCPServer,
} from "@/lib/tools/types";
import { useModal } from "@opal/components";
import { useUser } from "@/providers/UserProvider";
import { hasPermission } from "@/lib/permissions";
import { Permission } from "@/lib/types";
import { Button, Divider } from "@opal/components";
import type { ModalCreationInterface } from "@opal/components";
import { SvgCheckCircle, SvgServer, SvgUnplug } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";

interface AddMCPServerModalProps {
  skipOverlay?: boolean;
  activeServer: MCPServer | null;
  setActiveServer: (server: MCPServer | null) => void;
  disconnectModal: ModalCreationInterface;
  manageServerModal: ModalCreationInterface;
  onServerCreated?: (server: MCPServer) => void;
  handleAuthenticate: (serverId: number) => void;
  mutateMcpServers?: () => Promise<void>;
}

export default function AddMCPServerModal({
  skipOverlay = false,
  activeServer,
  disconnectModal,
  manageServerModal,
  onServerCreated,
  handleAuthenticate,
  mutateMcpServers,
}: AddMCPServerModalProps) {
  const t = useTranslations("actions");
  const { isOpen, toggle } = useModal();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const focusOnMount = useFocusOnMount<HTMLInputElement>();

  const { permissions } = useUser();

  const validationSchema = Yup.object().shape({
    name: Yup.string().required(t("addMcpModal.name.required")),
    description: Yup.string(),
    server_url: Yup.string()
      .url(t("addMcpModal.serverUrl.invalid"))
      .required(t("addMcpModal.serverUrl.required")),
  });

  // Use activeServer from props
  const server = activeServer;

  // Handler for disconnect button
  const handleDisconnectClick = () => {
    if (activeServer) {
      // Server stays the same, just toggle modals
      manageServerModal.toggle(false);
      disconnectModal.toggle(true);
    }
  };

  // Determine if we're in edit mode
  const isEditMode = !!server;

  const initialValues: MCPServerCreateRequest = {
    name: server?.name || "",
    description: server?.description || "",
    server_url: server?.server_url || "",
    is_public: server?.is_public ?? true,
    groups: server?.groups ?? [],
    users: server?.users ?? [],
  };

  const handleSubmit = async (values: MCPServerCreateRequest) => {
    setIsSubmitting(true);

    // A public server has no group restriction.
    const payload: MCPServerCreateRequest = {
      ...values,
      groups: values.is_public ? [] : values.groups,
      users: values.is_public ? [] : values.users,
    };

    try {
      if (isEditMode && server) {
        // Update existing server
        await updateMCPServer(server.id, payload);
        toast.success(t("addMcpModal.toasts.serverUpdated"));
        await mutateMcpServers?.();
      } else {
        // Create new server
        const createdServer = await createMCPServer(payload);

        toast.success(t("addMcpModal.toasts.serverCreated"));

        await mutateMcpServers?.();

        if (onServerCreated) {
          onServerCreated(createdServer);
        }
      }
      // Close modal. Do NOT clear `activeServer` here because this modal
      // frequently transitions to other modals (authenticate/disconnect), and
      // clearing would race those flows.
      toggle(false);
    } catch (error) {
      console.error(
        `Error ${isEditMode ? "updating" : "creating"} MCP server:`,
        error
      );
      toast.error(
        error instanceof Error
          ? error.message
          : isEditMode
            ? t("addMcpModal.toasts.updateFailed")
            : t("addMcpModal.toasts.createFailed")
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  // Handle modal close to clear server state
  const handleModalClose = (open: boolean) => {
    toggle(open);
  };

  return (
    <Modal open={isOpen} onOpenChange={handleModalClose}>
      <Modal.Content
        width="sm"
        height="lg"
        preventAccidentalClose={false}
        skipOverlay={skipOverlay}
      >
        <Formik
          initialValues={initialValues}
          validationSchema={validationSchema}
          onSubmit={handleSubmit}
        >
          {(formikProps) => (
            <Form>
              <Modal.Header
                icon={SvgServer}
                title={
                  isEditMode
                    ? t("addMcpModal.manageHeader.title")
                    : t("addMcpModal.addHeader.title")
                }
                description={
                  isEditMode
                    ? t("addMcpModal.manageHeader.description")
                    : t("addMcpModal.addHeader.description")
                }
                onClose={() => handleModalClose(false)}
              />

              <Modal.Body>
                <InputVertical
                  withLabel="name"
                  title={t("addMcpModal.name.title")}
                >
                  <InputTypeInField
                    name="name"
                    placeholder={t("addMcpModal.name.placeholder")}
                    ref={focusOnMount}
                  />
                </InputVertical>

                <InputVertical
                  withLabel="description"
                  title={t("addMcpModal.description.title")}
                  suffix={t("addMcpModal.description.suffix")}
                >
                  <InputTextAreaField
                    name="description"
                    placeholder={t("addMcpModal.description.placeholder")}
                    rows={3}
                  />
                </InputVertical>

                <Divider paddingParallel={0} paddingPerpendicular={0} />

                <InputVertical
                  withLabel="server_url"
                  title={t("addMcpModal.serverUrl.title")}
                  subDescription={t("addMcpModal.serverUrl.subDescription")}
                >
                  <InputTypeInField
                    name="server_url"
                    placeholder="https://your-mcp-server.com/mcp"
                  />
                </InputVertical>

                <Divider paddingParallel={0} paddingPerpendicular={0} />

                {/* Access control: who can add this server's tools to agents.
                    Self-gates on tier/role; no-op when groups are unavailable. */}
                <IsPublicGroupSelector
                  formikProps={formikProps}
                  objectName="MCP server"
                  isGlobalHolder={hasPermission(
                    permissions,
                    Permission.MANAGE_ACTIONS
                  )}
                  publicToWhom="Users"
                />

                {/* Authentication Status Section - Only show in edit mode when authenticated */}
                {isEditMode &&
                  server?.user_can_authenticate &&
                  server?.status === MCPServerStatus.CONNECTED && (
                    <Section
                      flexDirection="row"
                      justifyContent="between"
                      alignItems="start"
                      gap={4}
                    >
                      <Section gap={1} alignItems="start">
                        <Section
                          flexDirection="row"
                          gap={2}
                          alignItems="center"
                          width="fit"
                        >
                          <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
                          <Text>{t("addMcpModal.authStatus.title")}</Text>
                        </Section>
                        <Text secondaryBody text03>
                          {server.auth_type === "OAUTH"
                            ? t("addMcpModal.authStatus.oauthDescription", {
                                owner: server.owner,
                              })
                            : server.auth_type === "API_TOKEN"
                              ? t("addMcpModal.authStatus.apiTokenDescription")
                              : t(
                                  "addMcpModal.authStatus.connectedDescription"
                                )}
                        </Text>
                      </Section>
                      <Section
                        flexDirection="row"
                        gap={2}
                        alignItems="center"
                        width="fit"
                      >
                        <Button
                          icon={SvgUnplug}
                          prominence="tertiary"
                          type="button"
                          tooltip={t("addMcpModal.disconnectButton.tooltip")}
                          onClick={handleDisconnectClick}
                        />
                        <Button
                          prominence="secondary"
                          type="button"
                          onClick={() => {
                            // Close this modal and open the auth modal for this server
                            toggle(false);
                            handleAuthenticate(server.id);
                          }}
                        >
                          {t("addMcpModal.editConfigsButton.label")}
                        </Button>
                      </Section>
                    </Section>
                  )}
              </Modal.Body>

              <Modal.Footer>
                <Button
                  disabled={isSubmitting}
                  prominence="secondary"
                  type="button"
                  onClick={() => handleModalClose(false)}
                >
                  {t("addMcpModal.cancelButton.label")}
                </Button>
                <Button
                  disabled={
                    isSubmitting || !formikProps.isValid || !formikProps.dirty
                  }
                  type="submit"
                >
                  {isSubmitting
                    ? isEditMode
                      ? t("addMcpModal.submitButton.savingLabel")
                      : t("addMcpModal.submitButton.addingLabel")
                    : isEditMode
                      ? t("addMcpModal.submitButton.saveLabel")
                      : t("addMcpModal.submitButton.addLabel")}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
