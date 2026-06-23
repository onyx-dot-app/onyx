"use client";

import { useState, useMemo } from "react";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { useTranslation } from "react-i18next";
import Modal from "@/refresh-components/Modal";
import { InputVertical } from "@opal/layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import { createMCPServer, updateMCPServer } from "@/lib/tools/mcpService";
import {
  MCPServerCreateRequest,
  MCPServerStatus,
  MCPServer,
} from "@/lib/tools/interfaces";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { Button, Divider } from "@opal/components";
import { toast } from "@/hooks/useToast";
import { ModalCreationInterface } from "@/refresh-components/contexts/ModalContext";
import { SvgCheckCircle, SvgServer, SvgUnplug } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import i18n from "@/lib/i18n";

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

function getValidationSchema() {
  return Yup.object().shape({
    name: Yup.string().required(
      i18n.t("admin.actions_mcp.server_name_required")
    ),
    description: Yup.string(),
    server_url: Yup.string()
      .url(i18n.t("admin.actions_mcp.invalid_url"))
      .required(i18n.t("admin.actions_mcp.server_url_required")),
  });
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
  const { t } = useTranslation();
  const { isOpen, toggle } = useModal();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const validationSchema = useMemo(() => getValidationSchema(), []);

  const server = activeServer;

  const handleDisconnectClick = () => {
    if (activeServer) {
      manageServerModal.toggle(false);
      disconnectModal.toggle(true);
    }
  };

  const isEditMode = !!server;

  const initialValues: MCPServerCreateRequest = {
    name: server?.name || "",
    description: server?.description || "",
    server_url: server?.server_url || "",
  };

  const handleSubmit = async (values: MCPServerCreateRequest) => {
    setIsSubmitting(true);

    try {
      if (isEditMode && server) {
        await updateMCPServer(server.id, values);
        toast.success(t("admin.actions_mcp.update_success"));
        await mutateMcpServers?.();
      } else {
        const createdServer = await createMCPServer(values);

        toast.success(t("admin.actions_mcp.create_success"));

        await mutateMcpServers?.();

        if (onServerCreated) {
          onServerCreated(createdServer);
        }
      }
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
            ? t("admin.actions_mcp.update_failed")
            : t("admin.actions_mcp.create_failed")
      );
    } finally {
      setIsSubmitting(false);
    }
  };

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
          {({ isValid, dirty }) => (
            <Form>
              <Modal.Header
                icon={SvgServer}
                title={
                  isEditMode
                    ? t("admin.actions_mcp.modal_manage_title")
                    : t("admin.actions_mcp.modal_add_title")
                }
                description={
                  isEditMode
                    ? t("admin.actions_mcp.modal_manage_desc")
                    : t("admin.actions_mcp.modal_add_desc")
                }
                onClose={() => handleModalClose(false)}
              />

              <Modal.Body>
                <InputVertical
                  withLabel="name"
                  title={t("admin.actions_mcp.server_name")}
                >
                  <InputTypeInField
                    name="name"
                    placeholder={t("admin.actions_mcp.server_name_placeholder")}
                    autoFocus
                  />
                </InputVertical>

                <InputVertical
                  withLabel="description"
                  title={t("admin.actions_mcp.description")}
                  suffix={t("admin.llm.form.optional_suffix")}
                >
                  <InputTextAreaField
                    name="description"
                    placeholder={t("admin.actions_mcp.description_placeholder")}
                    rows={3}
                  />
                </InputVertical>

                <Divider paddingParallel="fit" paddingPerpendicular="fit" />

                <InputVertical
                  withLabel="server_url"
                  title={t("admin.actions_mcp.server_url")}
                  subDescription={t("admin.actions_mcp.server_url_desc")}
                >
                  <InputTypeInField
                    name="server_url"
                    placeholder={t("admin.actions_mcp.server_url_placeholder")}
                  />
                </InputVertical>

                {isEditMode &&
                  server?.is_authenticated &&
                  server?.status === MCPServerStatus.CONNECTED && (
                    <Section
                      flexDirection="row"
                      justifyContent="between"
                      alignItems="start"
                      gap={1}
                    >
                      <Section gap={0.25} alignItems="start">
                        <Section
                          flexDirection="row"
                          gap={0.5}
                          alignItems="center"
                          width="fit"
                        >
                          <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
                          <Text>{t("admin.actions_mcp.authenticated_connected")}</Text>
                        </Section>
                        <Text secondaryBody text03>
                          {server.auth_type === "OAUTH"
                            ? t("admin.actions_mcp.oauth_connected", {
                                owner: server.owner,
                              })
                            : server.auth_type === "API_TOKEN"
                              ? t("admin.actions_mcp.api_token_configured")
                              : t("admin.agents.connected")}
                        </Text>
                      </Section>
                      <Section
                        flexDirection="row"
                        gap={0.5}
                        alignItems="center"
                        width="fit"
                      >
                        <Button
                          icon={SvgUnplug}
                          prominence="tertiary"
                          type="button"
                          tooltip={t("admin.actions_mcp.disconnect_server")}
                          onClick={handleDisconnectClick}
                        />
                        <Button
                          prominence="secondary"
                          type="button"
                          onClick={() => {
                            toggle(false);
                            handleAuthenticate(server.id);
                          }}
                        >
                          {t("admin.actions_mcp.edit_configs")}
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
                  {t("general.cancel")}
                </Button>
                <Button
                  disabled={isSubmitting || !isValid || !dirty}
                  type="submit"
                >
                  {isSubmitting
                    ? isEditMode
                      ? t("admin.actions_mcp.saving")
                      : t("admin.actions_mcp.adding")
                    : isEditMode
                      ? t("admin.actions_mcp.save_changes")
                      : t("admin.actions_mcp.add_server_btn")}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
