"use client";

import { useState } from "react";
import { Formik, Form } from "formik";
import * as Yup from "yup";
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

const validationSchema = Yup.object().shape({
  name: Yup.string().required("请输入服务名称"),
  description: Yup.string(),
  server_url: Yup.string()
    .url("请输入有效 URL")
    .required("请输入服务 URL"),
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
        toast.success("MCP 服务已更新");
        await mutateMcpServers?.();
      } else {
        // Create new server
        const createdServer = await createMCPServer(values);

        toast.success("MCP 服务已创建");

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
          : `${isEditMode ? "更新" : "创建"} MCP 服务失败`
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
          {({ isValid, dirty }) => (
            <Form>
              <Modal.Header
                icon={SvgServer}
                title={isEditMode ? "管理 MCP 服务" : "添加 MCP 服务"}
                description={
                  isEditMode
                    ? "更新 MCP 服务配置并管理认证。"
                    : "连接 MCP (Model Context Protocol) 服务以添加自定义动作。"
                }
                onClose={() => handleModalClose(false)}
              />

              <Modal.Body>
                <InputVertical withLabel="name" title="服务名称">
                  <InputTypeInField
                    name="name"
                    placeholder="为 MCP 服务命名"
                    autoFocus
                  />
                </InputVertical>

                <InputVertical
                  withLabel="description"
                  title="描述"
                  suffix="可选"
                >
                  <InputTextAreaField
                    name="description"
                    placeholder="补充 MCP 服务详情"
                    rows={3}
                  />
                </InputVertical>

                <Divider paddingParallel="fit" paddingPerpendicular="fit" />

                <InputVertical
                  withLabel="server_url"
                  title="MCP 服务 URL"
                  subDescription="只连接你信任的服务。你需要对通过此连接执行的操作负责，并保持工具更新。"
                >
                  <InputTypeInField
                    name="server_url"
                    placeholder="https://your-mcp-server.com/mcp"
                  />
                </InputVertical>

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
                          <Text>已认证并连接</Text>
                        </Section>
                        <Text secondaryBody text03>
                          {server.auth_type === "OAUTH"
                            ? `OAuth connected to ${server.owner}`
                            : server.auth_type === "API_TOKEN"
                              ? "已配置 API token"
                              : "已连接"}
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
                          tooltip="断开服务"
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
                          编辑配置
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
                  取消
                </Button>
                <Button
                  disabled={isSubmitting || !isValid || !dirty}
                  type="submit"
                >
                  {isSubmitting
                    ? isEditMode
                      ? "正在保存..."
                      : "正在添加..."
                    : isEditMode
                      ? "保存更改"
                      : "添加服务"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
