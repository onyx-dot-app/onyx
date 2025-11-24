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
import { createMCPServer } from "@/lib/mcpService";
import { MCPServerCreateRequest } from "./types";
import { KeyedMutator } from "swr";
import { MCPServersResponse } from "@/lib/tools/interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { Separator } from "@/components/ui/separator";

interface AddMCPServerModalProps {
  mutateMcpServers: KeyedMutator<MCPServersResponse>;
  setPopup: (spec: PopupSpec) => void;
}

const validationSchema = Yup.object().shape({
  name: Yup.string().required("Server name is required"),
  description: Yup.string(),
  server_url: Yup.string()
    .url("Must be a valid URL")
    .required("Server URL is required"),
});

export default function AddMCPServerModal({
  mutateMcpServers,
  setPopup,
}: AddMCPServerModalProps) {
  const { isOpen, toggle } = useModal();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const initialValues: MCPServerCreateRequest = {
    name: "",
    description: "",
    server_url: "",
  };

  const handleSubmit = async (values: MCPServerCreateRequest) => {
    setIsSubmitting(true);

    try {
      await createMCPServer(values);
      setPopup({
        message: "MCP Server created successfully",
        type: "success",
      });

      // Refresh the servers list
      await mutateMcpServers();

      // Close modal
      toggle(false);
    } catch (error) {
      console.error("Error creating MCP server:", error);
      setPopup({
        message:
          error instanceof Error
            ? error.message
            : "Failed to create MCP server",
        type: "error",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal open={isOpen} onOpenChange={toggle}>
      <Modal.Content tall preventAccidentalClose={false}>
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
                <Modal.Title>Add MCP server</Modal.Title>
                <Modal.Description>
                  Connect MCP (Model Context Protocol) server to add custom
                  actions.
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
                  {isSubmitting ? "Adding..." : "Add Server"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
