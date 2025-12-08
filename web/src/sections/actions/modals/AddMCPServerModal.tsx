"use client";

import { useState } from "react";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import Modal from "@/refresh-components/Modal";
import { FormField } from "@/refresh-components/form/FormField";
import Button from "@/refresh-components/buttons/Button";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
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
  setActiveServer,
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
      // Close modal and clear server state
      toggle(false);
      setActiveServer(null);
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
    if (!open) {
      setActiveServer(null);
    }
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
          {({ values, errors, touched, handleChange, handleBlur, dirty }) => (
            <Form className="gap-0">
              <Modal.Header
                icon={SvgServer}
                title={isEditMode ? "Manage MCP server" : "Add MCP server"}
                description={
                  isEditMode
                    ? "Update your MCP server configuration and manage authentication."
                    : "Connect MCP (Model Context Protocol) server to add custom actions."
                }
                className="p-4 w-full"
                onClose={() => handleModalClose(false)}
              />

              <Modal.Body className="flex flex-col bg-background-tint-01 p-4 gap-4">
                <FormField
                  id="name"
                  name="name"
                  state={
                    errors.name && touched.name
                      ? "error"
                      : touched.name
                        ? "success"
                        : "idle"
                  }
                >
                  <FormField.Label>Server Name</FormField.Label>
                  <FormField.Control asChild>
                    <InputTypeIn
                      id="name"
                      name="name"
                      placeholder="Name your MCP server"
                      value={values.name}
                      onChange={handleChange}
                      onBlur={handleBlur}
                      autoFocus
                    />
                  </FormField.Control>
                  <FormField.Message
                    messages={{
                      error: errors.name,
                    }}
                  />
                </FormField>

                <FormField
                  id="description"
                  name="description"
                  state={
                    errors.description && touched.description
                      ? "error"
                      : touched.description
                        ? "success"
                        : "idle"
                  }
                >
                  <FormField.Label optional>Description</FormField.Label>
                  <FormField.Control asChild>
                    <InputTextArea
                      id="description"
                      name="description"
                      placeholder="More details about the MCP server"
                      value={values.description}
                      onChange={handleChange}
                      onBlur={handleBlur}
                      rows={3}
                      className="resize-none"
                    />
                  </FormField.Control>
                  <FormField.Message
                    messages={{
                      error: errors.description,
                    }}
                  />
                </FormField>

                <Separator className="py-0" />

                <FormField
                  id="server_url"
                  name="server_url"
                  state={
                    errors.server_url && touched.server_url
                      ? "error"
                      : touched.server_url
                        ? "success"
                        : "idle"
                  }
                >
                  <FormField.Label>MCP Server URL</FormField.Label>
                  <FormField.Control asChild>
                    <InputTypeIn
                      id="server_url"
                      name="server_url"
                      placeholder="https://your-mcp-server.com/mcp"
                      value={values.server_url}
                      onChange={handleChange}
                      onBlur={handleBlur}
                    />
                  </FormField.Control>
                  <FormField.Description>
                    Only connect to servers you trust. You are responsible for
                    actions taken with this connection and keeping your tools
                    updated.
                  </FormField.Description>
                  <FormField.Message
                    messages={{
                      error: errors.server_url,
                    }}
                  />
                </FormField>

                {/* Authentication Status Section - Only show in edit mode when authenticated */}
                {isEditMode &&
                  server?.is_authenticated &&
                  server?.status === MCPServerStatus.CONNECTED && (
                    <FormField state="idle">
                      <div className="flex items-start justify-between w-full">
                        <div className="flex-1 flex flex-col gap-0 items-start">
                          <FormField.Label
                            leftIcon={
                              <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
                            }
                          >
                            Authenticated & Connected
                          </FormField.Label>
                          <FormField.Description className="pl-5">
                            {server.auth_type === "OAUTH"
                              ? `OAuth connected to ${server.owner}`
                              : server.auth_type === "API_TOKEN"
                                ? "API token configured"
                                : "Connected"}
                          </FormField.Description>
                        </div>
                        <FormField.Control asChild>
                          <div className="flex gap-2 items-center justify-end">
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
                          </div>
                        </FormField.Control>
                      </div>
                    </FormField>
                  )}
              </Modal.Body>

              <Modal.Footer className="p-4 gap-2">
                <Button
                  secondary
                  type="button"
                  onClick={() => handleModalClose(false)}
                  disabled={isSubmitting}
                >
                  Cancel
                </Button>
                <Button primary type="submit" disabled={isSubmitting || !dirty}>
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
