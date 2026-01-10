"use client";

import { useState } from "react";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import Modal from "@/refresh-components/Modal";
import * as InputLayouts from "@/layouts/input-layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import Button from "@/refresh-components/buttons/Button";
import { createMCPServer, updateMCPServer } from "@/lib/tools/mcpService";
import {
  MCPServerCreateRequest,
  MCPServerStatus,
  MCPServer,
} from "@/lib/tools/interfaces";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import Separator from "@/refresh-components/Separator";
import IconButton from "@/refresh-components/buttons/IconButton";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { ModalCreationInterface } from "@/refresh-components/contexts/ModalContext";
import { SvgCheckCircle, SvgServer, SvgUnplug } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";

interface AddMCPServerModalProps {
  skipOverlay?: boolean;
  activeServer: MCPServer | null;
  setActiveServer: (server: MCPServer | null) => void;
  disconnectModal: ModalCreationInterface;
  manageServerModal: ModalCreationInterface;
  onServerCreated?: (server: MCPServer) => void;
  handleAuthenticate: (serverId: number) => void;
  setPopup?: (spec: PopupSpec) => void;
  mutateMcpServers?: () => Promise<void>;
}

const validationSchema = Yup.object().shape({
  name: Yup.string().required("Server name is required"),
  description: Yup.string(),
  server_url: Yup.string()
    .url("Must be a valid URL")
    .required("Server URL is required"),
});

export default function AddMCPServerModal({
  skipOverlay = false,
  activeServer,
  disconnectModal,
  manageServerModal,
  onServerCreated,
  handleAuthenticate,
  setPopup,
  mutateMcpServers,
}: AddMCPServerModalProps) {
  const { isOpen, toggle } = useModal();
  const [isSubmitting, setIsSubmitting] = useState(false);

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
  };

  const handleSubmit = async (values: MCPServerCreateRequest) => {
    setIsSubmitting(true);

    try {
      if (isEditMode && server) {
        // Update existing server
        await updateMCPServer(server.id, values);
        setPopup?.({
          message: "MCP Server updated successfully",
          type: "success",
        });
        await mutateMcpServers?.();
      } else {
        // Create new server
        const createdServer = await createMCPServer(values);

        setPopup?.({
          message: "MCP Server created successfully",
          type: "success",
        });

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
      setPopup?.({
        message:
          error instanceof Error
            ? error.message
            : `Failed to ${isEditMode ? "update" : "create"} MCP server`,
        type: "error",
      });
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
        tall
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
                title={isEditMode ? "Manage MCP Server" : "Add MCP Server"}
                description={
                  isEditMode
                    ? "Update your MCP server configuration and manage authentication."
                    : "Connect MCP (Model Context Protocol) server to add custom actions."
                }
                onClose={() => handleModalClose(false)}
              />

              <Modal.Body>
                <InputLayouts.Vertical name="name" label="Server Name">
                  <InputTypeInField
                    name="name"
                    placeholder="Name your MCP server"
                    autoFocus
                  />
                </InputLayouts.Vertical>

                <InputLayouts.Vertical
                  name="description"
                  label="Description"
                  optional
                >
                  <InputTextAreaField
                    name="description"
                    placeholder="More details about the MCP server"
                    rows={3}
                  />
                </InputLayouts.Vertical>

                <Separator noPadding />

                <InputLayouts.Vertical
                  name="server_url"
                  label="MCP Server URL"
                  subDescription="Only connect to servers you trust. You are responsible for actions taken with this connection and keeping your tools updated."
                >
                  <InputTypeInField
                    name="server_url"
                    placeholder="https://your-mcp-server.com/mcp"
                  />
                </InputLayouts.Vertical>

                {/* Authentication Status Section - Only show in edit mode when authenticated */}
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
                          fit
                        >
                          <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
                          <Text>Authenticated &amp; Connected</Text>
                        </Section>
                        <Text secondaryBody text03>
                          {server.auth_type === "OAUTH"
                            ? `OAuth connected to ${server.owner}`
                            : server.auth_type === "API_TOKEN"
                              ? "API token configured"
                              : "Connected"}
                        </Text>
                      </Section>
                      <Section
                        flexDirection="row"
                        gap={0.5}
                        alignItems="center"
                        fit
                      >
                        <IconButton
                          icon={SvgUnplug}
                          tertiary
                          type="button"
                          tooltip="Disconnect Server"
                          onClick={handleDisconnectClick}
                        />
                        <Button
                          secondary
                          type="button"
                          onClick={() => {
                            // Close this modal and open the auth modal for this server
                            toggle(false);
                            handleAuthenticate(server.id);
                          }}
                        >
                          Edit Configs
                        </Button>
                      </Section>
                    </Section>
                  )}
              </Modal.Body>

              <Modal.Footer>
                <Button
                  secondary
                  type="button"
                  onClick={() => handleModalClose(false)}
                  disabled={isSubmitting}
                >
                  Cancel
                </Button>
                <Button
                  primary
                  type="submit"
                  disabled={isSubmitting || !isValid || !dirty}
                >
                  {isSubmitting
                    ? isEditMode
                      ? "Saving..."
                      : "Adding..."
                    : isEditMode
                      ? "Save Changes"
                      : "Add Server"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
