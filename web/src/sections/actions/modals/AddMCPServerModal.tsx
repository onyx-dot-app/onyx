"use client";

import { useState } from "react";
import { Formik, Form } from "formik";
import useSWR from "swr";
import * as Yup from "yup";
import { InputSelect, MessageCard, Modal } from "@opal/components";
import { InputVertical, toast } from "@opal/layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import { createMCPServer, updateMCPServer } from "@/lib/tools/mcpService";
import {
  MCPServerCreateRequest,
  MCPServerStatus,
  MCPServer,
  MCPTransportType,
} from "@/lib/tools/interfaces";
import { useModal } from "@opal/components";
import { Button, Divider } from "@opal/components";
import type { ModalCreationInterface } from "@opal/components";
import { SvgCheckCircle, SvgServer, SvgUnplug } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";
import { FormField } from "@/refresh-components/form/FormField";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useSettings } from "@/lib/settings/hooks";
import { useCurrentUser } from "@/lib/users/hooks";
import { UserRole } from "@/lib/types";

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

interface MCPServerFormValues {
  name: string;
  description?: string;
  server_url: string;
  transport: MCPTransportType;
  stdio_command: string;
  stdio_args: string;
  stdio_env: string;
  is_public: boolean;
  groups: number[];
  users: string[];
}

const validationSchema = Yup.object().shape({
  name: Yup.string().required("Server name is required"),
  description: Yup.string(),
  server_url: Yup.string().when("transport", {
    is: (transport: MCPTransportType) => transport !== MCPTransportType.STDIO,
    then: (schema) =>
      schema.url("Must be a valid URL").required("Server URL is required"),
    otherwise: (schema) => schema.notRequired(),
  }),
  stdio_command: Yup.string().when("transport", {
    is: MCPTransportType.STDIO,
    then: (schema) => schema.required("Command is required"),
    otherwise: (schema) => schema.notRequired(),
  }),
  stdio_env: Yup.string().test(
    "stdio-env-json",
    "Environment must be a JSON object containing string values",
    (value, context) => {
      if (
        context.parent.transport !== MCPTransportType.STDIO ||
        !value?.trim()
      ) {
        return true;
      }
      try {
        const parsed = JSON.parse(value);
        return (
          parsed !== null &&
          typeof parsed === "object" &&
          !Array.isArray(parsed) &&
          Object.values(parsed).every((entry) => typeof entry === "string")
        );
      } catch {
        return false;
      }
    }
  ),
});

export default function AddMCPServerModal({
  skipOverlay = false,
  activeServer,
  disconnectModal,
  manageServerModal,
  onServerCreated,
  handleAuthenticate,
  mutateMcpServers,
}: AddMCPServerModalProps) {
  const { isOpen, toggle } = useModal();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const settings = useSettings();
  const { user } = useCurrentUser();

  // Use activeServer from props
  const server = activeServer;
  const { data: detailedServer } = useSWR<MCPServer>(
    server ? SWR_KEYS.adminMcpServer(server.id) : null,
    errorHandlingFetcher
  );
  const editableServer = detailedServer ?? server;
  const stdioEnabled =
    settings.mcp_stdio_enabled === true && user?.role === UserRole.ADMIN;

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

  const initialValues: MCPServerFormValues = {
    name: editableServer?.name || "",
    description: editableServer?.description || "",
    server_url: editableServer?.server_url || "",
    transport: editableServer?.transport || MCPTransportType.STREAMABLE_HTTP,
    stdio_command: editableServer?.stdio_command || "",
    stdio_args: (editableServer?.stdio_args || []).join("\n"),
    stdio_env: JSON.stringify(editableServer?.stdio_env || {}, null, 2),
    is_public: editableServer?.is_public ?? true,
    groups: editableServer?.groups ?? [],
    users: editableServer?.users ?? [],
  };

  const handleSubmit = async (values: MCPServerFormValues) => {
    setIsSubmitting(true);

    const isStdio = values.transport === MCPTransportType.STDIO;
    // A public server has no group restriction.
    const payload: MCPServerCreateRequest = {
      name: values.name,
      description: values.description,
      server_url: isStdio ? "" : values.server_url,
      transport: values.transport,
      stdio_command: isStdio ? values.stdio_command.trim() : undefined,
      stdio_args: isStdio
        ? values.stdio_args
            .split("\n")
            .map((arg) => arg.trim())
            .filter(Boolean)
        : [],
      stdio_env:
        isStdio && values.stdio_env.trim() ? JSON.parse(values.stdio_env) : {},
      is_public: values.is_public,
      groups: values.is_public ? [] : values.groups,
      users: values.is_public ? [] : values.users,
    };

    try {
      if (isEditMode && server) {
        // Update existing server
        await updateMCPServer(server.id, payload);
        toast.success("MCP Server updated successfully");
        await mutateMcpServers?.();
      } else {
        // Create new server
        const createdServer = await createMCPServer(payload);

        toast.success("MCP Server created successfully");

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
          : `Failed to ${isEditMode ? "update" : "create"} MCP server`
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
          enableReinitialize
        >
          {(formikProps) => (
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
                <InputVertical withLabel="name" title="Server Name">
                  <InputTypeInField
                    name="name"
                    placeholder="Name your MCP server"
                    autoFocus
                  />
                </InputVertical>

                <InputVertical
                  withLabel="description"
                  title="Description"
                  suffix="optional"
                >
                  <InputTextAreaField
                    name="description"
                    placeholder="More details about the MCP server"
                    rows={3}
                  />
                </InputVertical>

                <Divider paddingParallel="fit" paddingPerpendicular="fit" />

                {(stdioEnabled ||
                  editableServer?.transport === MCPTransportType.STDIO) && (
                  <FormField name="transport">
                    <FormField.Label>Transport</FormField.Label>
                    <FormField.Control asChild>
                      <InputSelect
                        value={formikProps.values.transport}
                        disabled={isEditMode}
                        onValueChange={(value) =>
                          formikProps.setFieldValue("transport", value)
                        }
                      >
                        <InputSelect.Trigger />
                        <InputSelect.Content>
                          <InputSelect.Item
                            value={MCPTransportType.STREAMABLE_HTTP}
                          >
                            Streamable HTTP
                          </InputSelect.Item>
                          {editableServer?.transport ===
                            MCPTransportType.SSE && (
                            <InputSelect.Item value={MCPTransportType.SSE}>
                              Server-sent events
                            </InputSelect.Item>
                          )}
                          <InputSelect.Item value={MCPTransportType.STDIO}>
                            Local process (stdio)
                          </InputSelect.Item>
                        </InputSelect.Content>
                      </InputSelect>
                    </FormField.Control>
                    {isEditMode && (
                      <FormField.Description>
                        Transport cannot be changed after creation.
                      </FormField.Description>
                    )}
                  </FormField>
                )}

                {formikProps.values.transport === MCPTransportType.STDIO ? (
                  <>
                    <MessageCard
                      title="Runs a process on the Onyx API host"
                      description="Only configure software you trust. Onyx executes the command directly without a shell, and shares these tools with the users or groups selected below."
                    />
                    <InputVertical withLabel="stdio_command" title="Command">
                      <InputTypeInField
                        name="stdio_command"
                        placeholder="/usr/local/bin/wordpress-mcp"
                      />
                    </InputVertical>
                    <InputVertical
                      withLabel="stdio_args"
                      title="Arguments"
                      suffix="optional, one per line"
                    >
                      <InputTextAreaField
                        name="stdio_args"
                        placeholder={"--site\nhttps://example.com"}
                        rows={3}
                      />
                    </InputVertical>
                    <InputVertical
                      withLabel="stdio_env"
                      title="Environment Variables"
                      suffix="optional JSON"
                      subDescription="Values are encrypted at rest. Existing values remain masked while editing."
                    >
                      <InputTextAreaField
                        name="stdio_env"
                        placeholder={'{\n  "WORDPRESS_TOKEN": "secret"\n}'}
                        rows={5}
                      />
                    </InputVertical>
                  </>
                ) : (
                  <InputVertical
                    withLabel="server_url"
                    title="MCP Server URL"
                    subDescription="Only connect to servers you trust. You are responsible for actions taken with this connection and keeping your tools updated."
                  >
                    <InputTypeInField
                      name="server_url"
                      placeholder="https://your-mcp-server.com/mcp"
                    />
                  </InputVertical>
                )}

                <Divider paddingParallel="fit" paddingPerpendicular="fit" />

                {/* Access control: who can add this server's tools to agents.
                    Self-gates on tier/role; no-op when groups are unavailable. */}
                <IsPublicGroupSelector
                  formikProps={formikProps}
                  objectName="MCP server"
                  publicToWhom="Users"
                />

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
                          width="fit"
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
                        width="fit"
                      >
                        <Button
                          icon={SvgUnplug}
                          prominence="tertiary"
                          type="button"
                          tooltip="Disconnect Server"
                          onClick={handleDisconnectClick}
                        />
                        {server.transport !== MCPTransportType.STDIO && (
                          <Button
                            prominence="secondary"
                            type="button"
                            onClick={() => {
                              // Close this modal and open the auth modal for this server
                              toggle(false);
                              handleAuthenticate(server.id);
                            }}
                          >
                            Edit Configs
                          </Button>
                        )}
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
                  Cancel
                </Button>
                <Button
                  disabled={
                    isSubmitting || !formikProps.isValid || !formikProps.dirty
                  }
                  type="submit"
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
