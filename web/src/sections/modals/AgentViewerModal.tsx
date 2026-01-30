"use client";

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

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { FullPersona } from "@/app/admin/assistants/interfaces";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import Modal from "@/refresh-components/Modal";
import { Section, LineItemLayout } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import Separator from "@/refresh-components/Separator";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import {
  SvgActions,
  SvgBubbleText,
  SvgExpand,
  SvgFileText,
  SvgFold,
  SvgFolder,
  SvgOrganization,
  SvgStar,
  SvgUser,
} from "@opal/icons";
import * as ExpandableCard from "@/layouts/expandable-card-layouts";
import * as ActionsLayouts from "@/layouts/actions-layouts";
import useMcpServersForAgentEditor from "@/hooks/useMcpServersForAgentEditor";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { MCPServer, ToolSnapshot } from "@/lib/tools/interfaces";
import EmptyMessage from "@/refresh-components/EmptyMessage";
import { Horizontal, Title } from "@/layouts/input-layouts";
import Switch from "@/refresh-components/inputs/Switch";
import Button from "@/refresh-components/buttons/Button";
import Hoverable, { HoverableContainer } from "@/refresh-components/Hoverable";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";

/**
 * Read-only MCP Server card for the viewer modal.
 * Displays the server header with its tools listed in the expandable content area.
 */
interface ViewerMCPServerCardProps {
  server: MCPServer;
  tools: ToolSnapshot[];
}

function ViewerMCPServerCard({ server, tools }: ViewerMCPServerCardProps) {
  const [folded, setFolded] = useState(false);
  const serverIcon = getActionIcon(server.server_url, server.name);

  return (
    <ExpandableCard.Root isFolded={folded} onFoldedChange={setFolded}>
      <ExpandableCard.Header>
        <div className="p-2">
          <LineItemLayout
            icon={serverIcon}
            title={server.name}
            description={server.description}
            variant="secondary"
            rightChildren={
              <Button
                internal
                rightIcon={folded ? SvgExpand : SvgFold}
                onClick={() => setFolded((prev) => !prev)}
              >
                {folded ? "Expand" : "Fold"}
              </Button>
            }
            center
          />
        </div>
      </ExpandableCard.Header>
      {tools.length > 0 && (
        <ActionsLayouts.Content>
          {tools.map((tool) => (
            <Section key={tool.id} padding={0.25}>
              <LineItemLayout
                title={tool.display_name}
                description={tool.description}
                variant="secondary"
              />
            </Section>
          ))}
        </ActionsLayouts.Content>
      )}
    </ExpandableCard.Root>
  );
}

/**
 * Read-only OpenAPI tool card for the viewer modal.
 * Displays just the tool header (no expandable content).
 */
function ViewerOpenApiToolCard({ tool }: { tool: ToolSnapshot }) {
  return (
    <ExpandableCard.Root>
      <ExpandableCard.Header>
        <div className="p-2">
          <LineItemLayout
            icon={SvgActions}
            title={tool.display_name}
            description={tool.description}
            variant="secondary"
            center
          />
        </div>
      </ExpandableCard.Header>
    </ExpandableCard.Root>
  );
}

export interface AgentViewerModalProps {
  agent: FullPersona;
}

export default function AgentViewerModal({ agent }: AgentViewerModalProps) {
  const agentViewerModal = useModal();
  const router = useRouter();

  const handleStarterClick = useCallback(
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

  return (
    <Modal
      open={agentViewerModal.isOpen}
      onOpenChange={agentViewerModal.toggle}
    >
      <Modal.Content width="md-sm" height="lg">
        <Modal.Header
          icon={(props) => <AgentAvatar agent={agent} {...props} size={24} />}
          title={agent.name}
          onClose={() => agentViewerModal.toggle(false)}
        />

        <Modal.Body>
          {/* Metadata */}
          <Section flexDirection="row" justifyContent="start">
            {!agent.is_default_persona && (
              <LineItemLayout
                icon={SvgStar}
                title="Featured"
                variant="tertiary"
                width="fit"
              />
            )}
            <LineItemLayout
              icon={SvgUser}
              title={agent.owner?.email ?? "Onyx"}
              variant="tertiary-muted"
              width="fit"
            />
            {agent.is_public && (
              <LineItemLayout
                icon={SvgOrganization}
                title="Public to your organization"
                variant="tertiary-muted"
                width="fit"
              />
            )}
          </Section>

          {/* Description */}
          {agent.description && <Text text03>{agent.description}</Text>}

          {/* Knowledge */}
          <Separator noPadding />
          <Section gap={0.5} alignItems="start">
            <Title title="Knowledge" />
            {hasKnowledge ? (
              <Section gap={0.25} alignItems="start">
                {agent.document_sets?.map((docSet) => (
                  <LineItemLayout
                    key={docSet.id}
                    icon={SvgFileText}
                    title={docSet.name}
                    variant="tertiary-muted"
                  />
                ))}
                {agent.hierarchy_nodes?.map((node) => (
                  <LineItemLayout
                    key={node.id}
                    icon={SvgFolder}
                    title={node.display_name}
                    description={node.source}
                    variant="tertiary-muted"
                  />
                ))}
                {agent.user_file_ids && agent.user_file_ids.length > 0 && (
                  <Text secondaryBody text03>
                    {agent.user_file_ids.length} uploaded file
                    {agent.user_file_ids.length > 1 ? "s" : ""}
                  </Text>
                )}
              </Section>
            ) : (
              <EmptyMessage title="No Knowledge" />
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
                <EmptyMessage title="No Actions" />
              )}
            </SimpleCollapsible.Content>
          </SimpleCollapsible>

          {/* More Info (Collapsible) */}
          <Separator noPadding />
          <SimpleCollapsible>
            <SimpleCollapsible.Header title="More Info" />
            <SimpleCollapsible.Content>
              <Section gap={0.5} alignItems="start">
                {agent.system_prompt && (
                  <LineItemLayout
                    title="Instructions"
                    description={agent.system_prompt}
                    variant="tertiary"
                  />
                )}
                {/*{agent.llm_model_version_override && (
                  <LineItemLayout
                    title="Model"
                    description={agent.llm_model_version_override}
                    variant="tertiary"
                  />
                )}*/}
                {/*{agent.search_start_date && (
                  <LineItemLayout
                    title="Instructions"
                    description={agent.search_start_date.toDateString()}
                    variant="tertiary"
                  />
                )}*/}
                <Horizontal
                  title="Overwrite System Prompts"
                  description='Remove the base system prompt which includes useful instructions (e.g. "You can use Markdown tables"). This may affect response quality.'
                  nonInteractive
                >
                  <Switch disabled checked={agent.replace_base_system_prompt} />
                </Horizontal>
              </Section>
            </SimpleCollapsible.Content>
          </SimpleCollapsible>

          {/* Prompt Reminders */}
          {agent.task_prompt && (
            <>
              <Separator noPadding />
              <Title title="Prompt Reminders" description={agent.task_prompt} />
            </>
          )}

          {/* Conversation Starters */}
          {agent.starter_messages && agent.starter_messages.length > 0 && (
            <>
              <Separator noPadding />
              <Title title="Prompt Reminders" />
              <div className="grid grid-cols-2 gap-1 w-full">
                {agent.starter_messages.map((starter, index) => (
                  <Hoverable
                    key={index}
                    onClick={() => handleStarterClick(starter.message)}
                    variant="secondary"
                    asChild
                  >
                    <HoverableContainer>
                      <LineItemLayout
                        icon={SvgBubbleText}
                        title={starter.message}
                        variant="tertiary-muted"
                      />
                    </HoverableContainer>
                  </Hoverable>
                ))}
              </div>
            </>
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
