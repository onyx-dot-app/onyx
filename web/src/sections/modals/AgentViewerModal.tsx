"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { FullPersona } from "@/app/admin/agents/interfaces";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import Modal from "@/refresh-components/Modal";
import { Section } from "@/layouts/general-layouts";
import {
  Card as CardLayout,
  Content,
  ContentAction,
  InputHorizontal,
} from "@opal/layouts";
import Text from "@/refresh-components/texts/Text";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { Card, Divider } from "@opal/components";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import {
  SvgActions,
  SvgBubbleText,
  SvgExpand,
  SvgFold,
  SvgOrganization,
  SvgStar,
  SvgUser,
} from "@opal/icons";
import useMcpServersForAgentEditor from "@/hooks/useMcpServersForAgentEditor";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { MCPServer, ToolSnapshot } from "@/lib/tools/interfaces";
import { EmptyMessageCard } from "@opal/components";
import Switch from "@/refresh-components/inputs/Switch";
import { Button } from "@opal/components";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";
import AppInputBar from "@/sections/input/AppInputBar";
import { useFilters, useLlmManager } from "@/lib/hooks";
import { formatMmDdYyyy } from "@/lib/dateUtils";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { FileCard } from "@/sections/cards/FileCard";
import DocumentSetCard from "@/sections/cards/DocumentSetCard";
import { getDisplayName } from "@/lib/llmConfig/utils";
import { useLLMProviders } from "@/hooks/useLLMProviders";
import { Interactive } from "@opal/core";

/**
 * Read-only MCP Server card for the viewer modal.
 * Displays the server header with its tools listed in the expandable content area.
 */
interface ViewerMCPServerCardProps {
  server: MCPServer;
  tools: ToolSnapshot[];
}

function ViewerMCPServerCard({ server, tools }: ViewerMCPServerCardProps) {
  const [expanded, setExpanded] = useState(true);
  const serverIcon = getActionIcon(server.server_url, server.name);

  return (
    <Card
      expandable
      expanded={expanded}
      border="solid"
      rounding="lg"
      padding="sm"
      expandedContent={
        tools.length > 0 ? (
          <div className="flex flex-col gap-2 p-2">
            {tools.map((tool) => (
              <Section key={tool.id} padding={0.25}>
                <Content
                  title={tool.display_name}
                  description={tool.description}
                  sizePreset="main-ui"
                  variant="section"
                />
              </Section>
            ))}
          </div>
        ) : undefined
      }
    >
      <CardLayout.Header
        headerChildren={
          <ContentAction
            icon={serverIcon}
            title={server.name}
            description={server.description}
            sizePreset="main-ui"
            variant="section"
            paddingVariant="fit"
          />
        }
        topRightChildren={
          <Button
            prominence="internal"
            rightIcon={expanded ? SvgFold : SvgExpand}
            onClick={() => setExpanded((prev) => !prev)}
          >
            {expanded ? "Fold" : "Expand"}
          </Button>
        }
      />
    </Card>
  );
}

/**
 * Read-only OpenAPI tool card for the viewer modal.
 * Displays just the tool header (no expandable content).
 */
function ViewerOpenApiToolCard({ tool }: { tool: ToolSnapshot }) {
  return (
    <Card border="solid" rounding="lg" padding="sm">
      <CardLayout.Header
        headerChildren={
          <Content
            icon={SvgActions}
            title={tool.display_name}
            description={tool.description}
            sizePreset="main-ui"
            variant="section"
          />
        }
      />
    </Card>
  );
}

/**
 * Floating ChatInputBar below the AgentViewerModal.
 * On submit, navigates to the agent's chat with the message pre-filled.
 */
interface AgentChatInputProps {
  agent: FullPersona;
  onSubmit: (message: string) => void;
}
function AgentChatInput({ agent, onSubmit }: AgentChatInputProps) {
  const llmManager = useLlmManager(undefined, agent);
  const filterManager = useFilters();

  return (
    <AppInputBar
      onSubmit={onSubmit}
      llmManager={llmManager}
      chatState="input"
      filterManager={filterManager}
      selectedAgent={agent}
      stopGenerating={() => {}}
      handleFileUpload={() => {}}
      currentSessionFileTokenCount={0}
      availableContextTokens={Infinity}
      deepResearchEnabled={false}
      toggleDeepResearch={() => {}}
      disabled={false}
    />
  );
}

/**
 * AgentViewerModal - A read-only view of an agent's configuration
 *
 * This modal is the view-only counterpart to `AgentEditorPage.tsx`. While
 * AgentEditorPage allows creating and editing agents with forms and inputs,
 * AgentViewerModal displays the same information in a read-only format.
 *
 * Key differences from AgentEditorPage:
 * - Modal presentation instead of full page
 * - Read-only display (no form inputs, switches, or editable fields)
 * - Static text/badges instead of form controls
 * - Designed to be opened from AgentCard when clicking on the card body
 *
 * Sections displayed (mirroring AgentEditorPage):
 * - Agent info: name, description, avatar
 * - Instructions (system prompt)
 * - Conversation starters
 * - Knowledge configuration
 * - Actions/tools
 * - Advanced options (model, sharing status)
 */
export interface AgentViewerModalProps {
  agent: FullPersona;
}
export default function AgentViewerModal({ agent }: AgentViewerModalProps) {
  const agentViewerModal = useModal();
  const router = useRouter();
  const { allRecentFiles } = useProjectsContext();
  const { llmProviders } = useLLMProviders(agent.id);

  const handleStartChat = useCallback(
    (message: string) => {
      const params = new URLSearchParams({
        [SEARCH_PARAM_NAMES.PERSONA_ID]: String(agent.id),
        [SEARCH_PARAM_NAMES.USER_PROMPT]: message,
        [SEARCH_PARAM_NAMES.SEND_ON_LOAD]: "true",
      });
      router.push(`/app?${params.toString()}` as Route);
      agentViewerModal.toggle(false);
    },
    [agent.id, router, agentViewerModal]
  );

  const hasKnowledge =
    (agent.document_sets && agent.document_sets.length > 0) ||
    (agent.hierarchy_nodes && agent.hierarchy_nodes.length > 0) ||
    (agent.user_file_ids && agent.user_file_ids.length > 0);

  // Categorize tools into MCP, OpenAPI, and built-in
  const mcpToolsByServerId = useMemo(() => {
    const map = new Map<number, ToolSnapshot[]>();
    agent.tools.forEach((tool) => {
      if (tool.mcp_server_id != null) {
        const existing = map.get(tool.mcp_server_id) || [];
        existing.push(tool);
        map.set(tool.mcp_server_id, existing);
      }
    });
    return map;
  }, [agent.tools]);

  const openApiTools = useMemo(
    () =>
      agent.tools.filter((t) => !t.in_code_tool_id && t.mcp_server_id == null),
    [agent.tools]
  );

  // Fetch MCP server metadata for display
  const { mcpData } = useMcpServersForAgentEditor();
  const mcpServers = mcpData?.mcp_servers ?? [];

  const mcpServersWithTools = useMemo(
    () =>
      mcpServers
        .filter((server) => mcpToolsByServerId.has(server.id))
        .map((server) => ({
          server,
          tools: mcpToolsByServerId.get(server.id)!,
        })),
    [mcpServers, mcpToolsByServerId]
  );

  const hasActions = mcpServersWithTools.length > 0 || openApiTools.length > 0;
  const defaultModel = getDisplayName(agent, llmProviders ?? []);

  return (
    <Modal
      open={agentViewerModal.isOpen}
      onOpenChange={agentViewerModal.toggle}
    >
      <Modal.Content
        width="lg"
        height="lg"
        bottomSlot={<AgentChatInput agent={agent} onSubmit={handleStartChat} />}
      >
        <Modal.Header
          icon={(props) => <AgentAvatar agent={agent} {...props} size={24} />}
          title={agent.name}
          onClose={() => agentViewerModal.toggle(false)}
        />

        <Modal.Body>
          {/* Metadata */}
          <Section flexDirection="row" justifyContent="start">
            {agent.is_featured && (
              <Content
                icon={SvgStar}
                title="Featured"
                sizePreset="main-ui"
                variant="body"
                widthVariant="fit"
              />
            )}
            <Content
              icon={SvgUser}
              title={agent.owner?.email ?? "Onyx"}
              sizePreset="main-ui"
              variant="body"
              prominence="muted"
              widthVariant="fit"
            />
            {agent.is_public && (
              <Content
                icon={SvgOrganization}
                title="Public to your organization"
                sizePreset="main-ui"
                variant="body"
                prominence="muted"
                widthVariant="fit"
              />
            )}
          </Section>

          {/* Description */}
          {agent.description && <Text text03>{agent.description}</Text>}

          {/* Knowledge */}
          <Divider paddingParallel="fit" paddingPerpendicular="fit" />
          <Section gap={0.5} alignItems="start">
            <Content
              title="Knowledge"
              sizePreset="main-content"
              variant="section"
            />
            {hasKnowledge ? (
              <Section
                gap={0.5}
                flexDirection="row"
                justifyContent="start"
                wrap
                alignItems="start"
              >
                {agent.document_sets?.map((docSet) => (
                  <DocumentSetCard key={docSet.id} documentSet={docSet} />
                ))}
                {agent.user_file_ids?.map((fileId) => {
                  const file = allRecentFiles.find((f) => f.id === fileId);
                  if (!file) return null;
                  return <FileCard key={fileId} file={file} />;
                })}
              </Section>
            ) : (
              <EmptyMessageCard sizePreset="main-ui" title="No Knowledge" />
            )}
          </Section>

          {/* Actions & Tools */}
          <SimpleCollapsible>
            <SimpleCollapsible.Header title="Actions & Tools" />
            <SimpleCollapsible.Content>
              {hasActions ? (
                <Section gap={0.5} alignItems="start">
                  {mcpServersWithTools.map(({ server, tools }) => (
                    <ViewerMCPServerCard
                      key={server.id}
                      server={server}
                      tools={tools}
                    />
                  ))}
                  {openApiTools.map((tool) => (
                    <ViewerOpenApiToolCard key={tool.id} tool={tool} />
                  ))}
                </Section>
              ) : (
                <EmptyMessageCard sizePreset="main-ui" title="No Actions" />
              )}
            </SimpleCollapsible.Content>
          </SimpleCollapsible>

          {/* More Info (Collapsible) */}
          <Divider paddingParallel="fit" paddingPerpendicular="fit" />
          <SimpleCollapsible>
            <SimpleCollapsible.Header title="More Info" />
            <SimpleCollapsible.Content>
              <Section gap={0.5} alignItems="start">
                {agent.system_prompt && (
                  <Content
                    title="Instructions"
                    description={agent.system_prompt}
                    sizePreset="main-ui"
                    variant="section"
                  />
                )}
                {defaultModel && (
                  <InputHorizontal
                    title="Default Model"
                    description="This model will be used by Onyx by default in your chats."
                  >
                    <Text>{defaultModel}</Text>
                  </InputHorizontal>
                )}
                {agent.search_start_date && (
                  <InputHorizontal
                    title="Knowledge Cutoff Date"
                    description="Documents with a last-updated date prior to this will be ignored."
                  >
                    <Text mainUiMono>
                      {formatMmDdYyyy(agent.search_start_date)}
                    </Text>
                  </InputHorizontal>
                )}
                <InputHorizontal
                  title="Overwrite System Prompts"
                  description='Remove the base system prompt which includes useful instructions (e.g. "You can use Markdown tables"). This may affect response quality.'
                  withLabel
                >
                  <Switch disabled checked={agent.replace_base_system_prompt} />
                </InputHorizontal>
              </Section>
            </SimpleCollapsible.Content>
          </SimpleCollapsible>

          {/* Prompt Reminders */}
          {agent.task_prompt && (
            <>
              <Divider paddingParallel="fit" paddingPerpendicular="fit" />
              <Content
                title="Prompt Reminders"
                description={agent.task_prompt}
                sizePreset="main-content"
                variant="section"
              />
            </>
          )}

          {/* Conversation Starters */}
          {agent.starter_messages && agent.starter_messages.length > 0 && (
            <>
              <Divider paddingParallel="fit" paddingPerpendicular="fit" />
              <Content
                title="Conversation Starters"
                sizePreset="main-content"
                variant="section"
              />
              <div className="grid grid-cols-2 gap-1 w-full">
                {agent.starter_messages.map((starter, index) => (
                  <Interactive.Stateless
                    key={index}
                    onClick={() => handleStartChat(starter.message)}
                    prominence="tertiary"
                  >
                    <Interactive.Container>
                      <Content
                        icon={SvgBubbleText}
                        title={starter.message}
                        sizePreset="main-ui"
                        variant="body"
                        prominence="muted"
                        widthVariant="full"
                      />
                    </Interactive.Container>
                  </Interactive.Stateless>
                ))}
              </div>
            </>
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
