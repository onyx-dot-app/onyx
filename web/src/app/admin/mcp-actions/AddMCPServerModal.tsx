"use client";

import { useState } from "react";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import Modal from "@/refresh-components/Modal";
import { FormField } from "@/refresh-components/form/FormField";
import Button from "@/refresh-components/buttons/Button";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { Textarea } from "@/components/ui/textarea";
import SvgServer from "@/icons/server";
import SvgCheckCircle from "@/icons/check-circle";
import SvgMoreHorizontal from "@/icons/more-horizontal";
import { createMCPServer, updateMCPServer } from "@/lib/mcpService";
import { MCPServerCreateRequest, MCPServerWithStatus } from "./types";
import { KeyedMutator } from "swr";
import { MCPServersResponse } from "@/lib/tools/interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { Separator } from "@/components/ui/separator";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgUnplug from "@/icons/unplug";

interface AddMCPServerModalProps {
  server?: MCPServerWithStatus;
  mutateMcpServers: KeyedMutator<MCPServersResponse>;
  setPopup: (spec: PopupSpec) => void;
  onDisconnect?: () => void;
  skipOverlay?: boolean;
}

const validationSchema = Yup.object().shape({
  name: Yup.string().required("Server name is required"),
  description: Yup.string(),
  server_url: Yup.string()
    .url("Must be a valid URL")
    .required("Server URL is required"),
});

export default function AddMCPServerModal({
  server,
  mutateMcpServers,
  setPopup,
  onDisconnect,
  skipOverlay = false,
}: AddMCPServerModalProps) {
  const { isOpen, toggle } = useModal();
  const [isSubmitting, setIsSubmitting] = useState(false);

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
        setPopup({
          message: "MCP Server updated successfully",
          type: "success",
        });
      } else {
        // Create new server
        await createMCPServer(values);
        setPopup({
          message: "MCP Server created successfully",
          type: "success",
        });
      }

      // Refresh the servers list
      await mutateMcpServers();

      // Close modal
      toggle(false);
    } catch (error) {
      console.error(
        `Error ${isEditMode ? "updating" : "creating"} MCP server:`,
        error
      );
      setPopup({
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

  return (
    <Modal open={isOpen} onOpenChange={toggle}>
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
          {({ values, errors, touched, handleChange, handleBlur }) => (
            <Form className="gap-0">
              <Modal.Header className="p-4 w-full">
                <Modal.CloseButton />
                <Modal.Icon icon={SvgServer} className="mb-1" />
                <Modal.Title>
                  {isEditMode ? "Manage MCP server" : "Add MCP server"}
                </Modal.Title>
                <Modal.Description>
                  {isEditMode
                    ? "Update your MCP server configuration and manage authentication."
                    : "Connect MCP (Model Context Protocol) server to add custom actions."}
                </Modal.Description>
              </Modal.Header>

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
                    <Textarea
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

                <Separator className="my-0 bg-border-01" />

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
                {isEditMode && server?.is_authenticated && (
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
                            onClick={() => {
                              if (onDisconnect) {
                                onDisconnect();
                              }
                            }}
                          />
                          <Button
                            secondary
                            type="button"
                            onClick={() => {
                              // Edit configs functionality - to be added later
                              console.log("Edit configs clicked");
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
                  onClick={() => toggle(false)}
                  disabled={isSubmitting}
                >
                  Cancel
                </Button>
                <Button primary type="submit" disabled={isSubmitting}>
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
