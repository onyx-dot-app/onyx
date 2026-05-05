"use client";

import { useState } from "react";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { Button as OpalButton } from "@opal/components";
import { FieldArray, useFormikContext } from "formik";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInElementField from "@/refresh-components/form/InputTypeInElementField";
import InputDatePickerField from "@/refresh-components/form/InputDatePickerField";
import Message from "@/refresh-components/messages/Message";
import Separator from "@/refresh-components/Separator";
import * as InputLayouts from "@/layouts/input-layouts";
import LLMSelector from "@/components/llm/LLMSelector";
import {
  STARTER_MESSAGES_EXAMPLES,
  MAX_CHARACTERS_STARTER_MESSAGE,
} from "@/lib/constants";
import Text from "@/refresh-components/texts/Text";
import { Card } from "@/refresh-components/cards";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import SwitchField from "@/refresh-components/form/SwitchField";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { DocumentSetSummary } from "@/lib/types";
import {
  SvgActions,
  SvgExpand,
  SvgFold,
  SvgLock,
  SvgSliders,
  SvgUsers,
} from "@opal/icons";
import * as ActionsLayouts from "@/layouts/actions-layouts";
import * as ExpandableCard from "@/layouts/expandable-card-layouts";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { MCPServer, MCPTool, ToolSnapshot } from "@/lib/tools/interfaces";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import useFilter from "@/hooks/useFilter";
import EnabledCount from "@/refresh-components/EnabledCount";
import AgentKnowledgePane from "@/sections/knowledge/AgentKnowledgePane";
import { ValidSources } from "@/lib/types";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { ProjectFile } from "@/app/app/projects/projectsService";
import { FullPersona } from "@/app/admin/agents/interfaces";
import type { LLMProviderDescriptor } from "@/interfaces/llm";

// ---------------------------------------------------------------------------
// Local sub-components (moved from AgentEditorPage)
// ---------------------------------------------------------------------------

function StarterMessages() {
  const max_starters = STARTER_MESSAGES_EXAMPLES.length;

  const { values } = useFormikContext<{
    starter_messages: string[];
  }>();

  const starters = values.starter_messages || [];

  // Count how many non-empty starters we have
  const filledStarters = starters.filter((s) => s).length;
  const canAddMore = filledStarters < max_starters;

  // Show at least 1, or all filled ones, or filled + 1 empty (up to max)
  const visibleCount = Math.min(
    max_starters,
    Math.max(
      1,
      filledStarters === 0 ? 1 : filledStarters + (canAddMore ? 1 : 0)
    )
  );

  return (
    <FieldArray name="starter_messages">
      {(arrayHelpers) => (
        <GeneralLayouts.Section gap={0.5}>
          {Array.from({ length: visibleCount }, (_, i) => (
            <InputTypeInElementField
              key={`starter_messages.${i}`}
              name={`starter_messages.${i}`}
              placeholder={
                STARTER_MESSAGES_EXAMPLES[i] ||
                "Enter a conversation starter..."
              }
              onRemove={() => arrayHelpers.remove(i)}
            />
          ))}
        </GeneralLayouts.Section>
      )}
    </FieldArray>
  );
}

interface OpenApiToolCardProps {
  tool: ToolSnapshot;
}

function OpenApiToolCard({ tool }: OpenApiToolCardProps) {
  const toolFieldName = `openapi_tool_${tool.id}`;

  return (
    <ExpandableCard.Root defaultFolded>
      <ActionsLayouts.Header
        title={tool.display_name || tool.name}
        description={tool.description}
        icon={SvgActions}
        rightChildren={<SwitchField name={toolFieldName} />}
      />
    </ExpandableCard.Root>
  );
}

interface MCPServerCardProps {
  server: MCPServer;
  tools: MCPTool[];
  isLoading: boolean;
}

function MCPServerCard({
  server,
  tools: enabledTools,
  isLoading,
}: MCPServerCardProps) {
  const [isFolded, setIsFolded] = useState(false);
  const { values, setFieldValue, getFieldMeta } = useFormikContext<any>();
  const serverFieldName = `mcp_server_${server.id}`;
  const isServerEnabled = values[serverFieldName]?.enabled ?? false;
  const {
    query,
    setQuery,
    filtered: filteredTools,
  } = useFilter(enabledTools, (tool) => `${tool.name} ${tool.description}`);

  // Calculate enabled and total tool counts
  const enabledCount = enabledTools.filter((tool) => {
    const toolFieldValue = values[serverFieldName]?.[`tool_${tool.id}`];
    return toolFieldValue === true;
  }).length;

  return (
    <ExpandableCard.Root isFolded={isFolded} onFoldedChange={setIsFolded}>
      <ActionsLayouts.Header
        title={server.name}
        description={server.description}
        icon={getActionIcon(server.server_url, server.name)}
        rightChildren={
          <GeneralLayouts.Section
            flexDirection="row"
            gap={0.5}
            alignItems="start"
          >
            <EnabledCount
              enabledCount={enabledCount}
              totalCount={enabledTools.length}
            />
            <SwitchField
              name={`${serverFieldName}.enabled`}
              onCheckedChange={(checked) => {
                enabledTools.forEach((tool) => {
                  setFieldValue(`${serverFieldName}.tool_${tool.id}`, checked);
                });
                if (!checked) return;
                setIsFolded(false);
              }}
            />
          </GeneralLayouts.Section>
        }
      >
        <GeneralLayouts.Section flexDirection="row" gap={0.5}>
          <InputTypeIn
            placeholder="Search tools..."
            variant="internal"
            leftSearchIcon
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {enabledTools.length > 0 && (
            <OpalButton
              prominence="internal"
              rightIcon={isFolded ? SvgExpand : SvgFold}
              onClick={() => setIsFolded((prev) => !prev)}
            >
              {isFolded ? "Expand" : "Fold"}
            </OpalButton>
          )}
        </GeneralLayouts.Section>
      </ActionsLayouts.Header>
      {isLoading ? (
        <ActionsLayouts.Content>
          <GeneralLayouts.Section padding={1}>
            <SimpleLoader />
          </GeneralLayouts.Section>
        </ActionsLayouts.Content>
      ) : (
        enabledTools.length > 0 &&
        filteredTools.length > 0 && (
          <ActionsLayouts.Content>
            {filteredTools.map((tool) => (
              <ActionsLayouts.Tool
                key={tool.id}
                name={`${serverFieldName}.tool_${tool.id}`}
                title={tool.name}
                description={tool.description}
                icon={tool.icon ?? SvgSliders}
                disabled={
                  !tool.isAvailable ||
                  !getFieldMeta<boolean>(`${serverFieldName}.enabled`).value
                }
                rightChildren={
                  <SwitchField
                    name={`${serverFieldName}.tool_${tool.id}`}
                    disabled={!isServerEnabled}
                  />
                }
              />
            ))}
          </ActionsLayouts.Content>
        )
      )}
    </ExpandableCard.Root>
  );
}

// ---------------------------------------------------------------------------
// AgentFormBody props
// ---------------------------------------------------------------------------

export interface MCPServerWithTools {
  server: MCPServer;
  tools: MCPTool[];
  isLoading: boolean;
}

export interface AgentFormBodyProps {
  /** Render slot for the avatar editor — AgentIconEditor stays in the parent */
  avatarEditor: React.ReactNode;

  /** Existing agent being edited, or undefined/null for create mode */
  existingAgent?: FullPersona | null;

  // -- Knowledge section --
  allRecentFiles: ProjectFile[];
  documentSets: DocumentSetSummary[];
  onFileClick: (file: ProjectFile) => void;
  onUploadChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  hasProcessingFiles: boolean;
  vectorDbEnabled: boolean;

  // -- Actions section --
  mcpServersWithTools: MCPServerWithTools[];
  mcpServers: MCPServer[];
  openApiTools: ToolSnapshot[];
  isImageGenerationAvailable: boolean;
  imageGenerationDisabledTooltip?: string;
  webSearchTool: ToolSnapshot | undefined;
  openURLTool: ToolSnapshot | undefined;
  codeInterpreterTool: ToolSnapshot | undefined;

  // -- Advanced section --
  llmProviders: LLMProviderDescriptor[];
  getCurrentLlm: (values: any, llmProviders: any) => string | null;
  onLlmSelect: (selected: string | null, setFieldValue: any) => void;
  canUpdateFeaturedStatus: boolean;
  onShareClick: () => void;
  onDeleteClick: () => void;

  // -- Wizard highlight support --
  highlightedFields?: Set<string>;
}

// ---------------------------------------------------------------------------
// AgentFormBody component
// ---------------------------------------------------------------------------

export default function AgentFormBody({
  avatarEditor,
  existingAgent,
  allRecentFiles,
  documentSets,
  onFileClick,
  onUploadChange,
  hasProcessingFiles,
  vectorDbEnabled,
  mcpServersWithTools,
  mcpServers,
  openApiTools,
  isImageGenerationAvailable,
  imageGenerationDisabledTooltip,
  webSearchTool,
  openURLTool,
  codeInterpreterTool,
  llmProviders,
  getCurrentLlm,
  onLlmSelect,
  canUpdateFeaturedStatus,
  onShareClick,
  onDeleteClick,
  highlightedFields,
}: AgentFormBodyProps) {
  const { values, setFieldValue } = useFormikContext<any>();

  const isShared =
    values.is_public ||
    values.shared_user_ids?.length > 0 ||
    values.shared_group_ids?.length > 0;

  /** Wrap a section in a subtle highlight when the field name is in the set */
  function highlight(fieldName: string, children: React.ReactNode) {
    if (!highlightedFields?.has(fieldName)) return children;
    return (
      <div className="rounded-12 bg-status-info-00 border border-status-info-02 transition-all duration-500 -mx-2 px-2">
        {children}
      </div>
    );
  }

  return (
    <>
      {highlight(
        "name",
        <GeneralLayouts.Section flexDirection="row" gap={2.5} alignItems="start">
          <GeneralLayouts.Section>
            <InputLayouts.Vertical name="name" title="Name">
              <InputTypeInField name="name" placeholder="Name your agent" />
            </InputLayouts.Vertical>

            <InputLayouts.Vertical
              name="description"
              title="Description"
              suffix="optional"
            >
              <InputTextAreaField
                name="description"
                placeholder="What does this agent do?"
              />
            </InputLayouts.Vertical>
          </GeneralLayouts.Section>

          <GeneralLayouts.Section width="fit">
            <InputLayouts.Vertical name="agent_avatar" title="Agent Avatar">
              {avatarEditor}
            </InputLayouts.Vertical>
          </GeneralLayouts.Section>
        </GeneralLayouts.Section>
      )}

      <Separator noPadding />

      {highlight(
        "instructions",
        <GeneralLayouts.Section>
          <InputLayouts.Vertical
            name="instructions"
            title="Instructions"
            suffix="optional"
            description="Add instructions to tailor the response for this agent."
          >
            <InputTextAreaField
              name="instructions"
              placeholder="Think step by step and show reasoning for complex problems. Use specific examples. Emphasize action items, and leave blanks for the human to fill in when you have unknown. Use a polite enthusiastic tone."
            />
          </InputLayouts.Vertical>

          <InputLayouts.Vertical
            name="starter_messages"
            title="Conversation Starters"
            description="Example messages that help users understand what this agent can do and how to interact with it effectively."
            suffix="optional"
          >
            <StarterMessages />
          </InputLayouts.Vertical>
        </GeneralLayouts.Section>
      )}

      <Separator noPadding />

      {highlight(
        "knowledge",
        <AgentKnowledgePane
          enableKnowledge={values.enable_knowledge}
          onEnableKnowledgeChange={(enabled) =>
            setFieldValue("enable_knowledge", enabled)
          }
          selectedSources={values.selected_sources}
          onSourcesChange={(sources) =>
            setFieldValue("selected_sources", sources)
          }
          documentSets={documentSets ?? []}
          selectedDocumentSetIds={values.document_set_ids}
          onDocumentSetIdsChange={(ids) =>
            setFieldValue("document_set_ids", ids)
          }
          selectedDocumentIds={values.document_ids}
          onDocumentIdsChange={(ids) => setFieldValue("document_ids", ids)}
          selectedFolderIds={values.hierarchy_node_ids}
          onFolderIdsChange={(ids) =>
            setFieldValue("hierarchy_node_ids", ids)
          }
          selectedFileIds={values.user_file_ids}
          onFileIdsChange={(ids) => setFieldValue("user_file_ids", ids)}
          allRecentFiles={allRecentFiles}
          onFileClick={onFileClick}
          onUploadChange={onUploadChange}
          hasProcessingFiles={hasProcessingFiles}
          initialAttachedDocuments={existingAgent?.attached_documents}
          initialHierarchyNodes={existingAgent?.hierarchy_nodes}
          vectorDbEnabled={vectorDbEnabled}
        />
      )}

      <Separator noPadding />

      {highlight(
        "actions",
        <SimpleCollapsible>
          <SimpleCollapsible.Header
            title="Actions"
            description="Tools and capabilities available for this agent to use."
          />
          <SimpleCollapsible.Content>
            <GeneralLayouts.Section gap={0.5}>
              <SimpleTooltip
                tooltip={imageGenerationDisabledTooltip}
                side="top"
              >
                <Card
                  variant={
                    isImageGenerationAvailable ? undefined : "disabled"
                  }
                >
                  <InputLayouts.Horizontal
                    name="image_generation"
                    title="Image Generation"
                    description="Generate and manipulate images using AI-powered tools."
                    disabled={!isImageGenerationAvailable}
                  >
                    <SwitchField
                      name="image_generation"
                      disabled={!isImageGenerationAvailable}
                    />
                  </InputLayouts.Horizontal>
                </Card>
              </SimpleTooltip>

              <Card variant={!!webSearchTool ? undefined : "disabled"}>
                <InputLayouts.Horizontal
                  name="web_search"
                  title="Web Search"
                  description="Search the web for real-time information and up-to-date results."
                  disabled={!webSearchTool}
                >
                  <SwitchField name="web_search" disabled={!webSearchTool} />
                </InputLayouts.Horizontal>
              </Card>

              <Card variant={!!openURLTool ? undefined : "disabled"}>
                <InputLayouts.Horizontal
                  name="open_url"
                  title="Open URL"
                  description="Fetch and read content from web URLs."
                  disabled={!openURLTool}
                >
                  <SwitchField name="open_url" disabled={!openURLTool} />
                </InputLayouts.Horizontal>
              </Card>

              <Card
                variant={!!codeInterpreterTool ? undefined : "disabled"}
              >
                <InputLayouts.Horizontal
                  name="code_interpreter"
                  title="Code Interpreter"
                  description="Generate and run code."
                  disabled={!codeInterpreterTool}
                >
                  <SwitchField
                    name="code_interpreter"
                    disabled={!codeInterpreterTool}
                  />
                </InputLayouts.Horizontal>
              </Card>

              {/* Tools */}
              <>
                {/* render the separator if there is at least one mcp-server or open-api-tool */}
                {(mcpServers.length > 0 || openApiTools.length > 0) && (
                  <Separator noPadding className="py-1" />
                )}

                {/* MCP tools */}
                {mcpServersWithTools.length > 0 && (
                  <GeneralLayouts.Section gap={0.5}>
                    {mcpServersWithTools.map(
                      ({ server, tools, isLoading }) => (
                        <MCPServerCard
                          key={server.id}
                          server={server}
                          tools={tools}
                          isLoading={isLoading}
                        />
                      )
                    )}
                  </GeneralLayouts.Section>
                )}

                {/* OpenAPI tools */}
                {openApiTools.length > 0 && (
                  <GeneralLayouts.Section gap={0.5}>
                    {openApiTools.map((tool) => (
                      <OpenApiToolCard key={tool.id} tool={tool} />
                    ))}
                  </GeneralLayouts.Section>
                )}
              </>
            </GeneralLayouts.Section>
          </SimpleCollapsible.Content>
        </SimpleCollapsible>
      )}

      <Separator noPadding />

      {highlight(
        "advanced",
        <SimpleCollapsible>
          <SimpleCollapsible.Header
            title="Advanced Options"
            description="Fine-tune agent prompts and knowledge."
          />
          <SimpleCollapsible.Content>
            <GeneralLayouts.Section>
              <Card>
                <InputLayouts.Horizontal
                  title="Share This Agent"
                  description="with other users, groups, or everyone in your organization."
                  center
                >
                  <OpalButton
                    prominence="secondary"
                    icon={isShared ? SvgUsers : SvgLock}
                    onClick={onShareClick}
                  >
                    Share
                  </OpalButton>
                </InputLayouts.Horizontal>
                {canUpdateFeaturedStatus && (
                  <>
                    <InputLayouts.Horizontal
                      name="is_featured"
                      title="Feature This Agent"
                      description="Show this agent at the top of the explore agents list and automatically pin it to the sidebar for new users with access."
                    >
                      <SwitchField name="is_featured" />
                    </InputLayouts.Horizontal>
                    {values.is_featured && !isShared && (
                      <Message
                        static
                        close={false}
                        className="w-full"
                        text="This agent is private to you and will only be featured for yourself."
                      />
                    )}
                  </>
                )}
              </Card>

              <Card>
                <InputLayouts.Horizontal
                  name="llm_model"
                  title="Default Model"
                  description="This model will be used by Meaningful AI by default in your chats."
                >
                  <LLMSelector
                    name="llm_model"
                    llmProviders={llmProviders ?? []}
                    currentLlm={getCurrentLlm(values, llmProviders)}
                    onSelect={(selected) =>
                      onLlmSelect(selected, setFieldValue)
                    }
                  />
                </InputLayouts.Horizontal>
                <InputLayouts.Horizontal
                  name="knowledge_cutoff_date"
                  title="Knowledge Cutoff Date"
                  suffix="optional"
                  description="Documents with a last-updated date prior to this will be ignored."
                >
                  <InputDatePickerField
                    name="knowledge_cutoff_date"
                    maxDate={new Date()}
                  />
                </InputLayouts.Horizontal>
                <InputLayouts.Horizontal
                  name="replace_base_system_prompt"
                  title="Overwrite System Prompt"
                  suffix="(Not Recommended)"
                  description='Remove the base system prompt which includes useful instructions (e.g. "You can use Markdown tables"). This may affect response quality.'
                >
                  <SwitchField name="replace_base_system_prompt" />
                </InputLayouts.Horizontal>
              </Card>

              <GeneralLayouts.Section gap={0.25}>
                <InputLayouts.Vertical
                  name="reminders"
                  title="Reminders"
                  suffix="optional"
                >
                  <InputTextAreaField
                    name="reminders"
                    placeholder="Remember, I want you to always format your response as a numbered list."
                  />
                </InputLayouts.Vertical>
                <Text text03 secondaryBody>
                  Append a brief reminder to the prompt messages. Use this to
                  remind the agent if you find that it tends to forget certain
                  instructions as the chat progresses. This should be brief
                  and not interfere with the user messages.
                </Text>
              </GeneralLayouts.Section>
            </GeneralLayouts.Section>
          </SimpleCollapsible.Content>
        </SimpleCollapsible>
      )}

      {existingAgent && (
        <>
          <Separator noPadding />

          <Card>
            <InputLayouts.Horizontal
              title="Delete This Agent"
              description="Anyone using this agent will no longer be able to access it."
              center
            >
              <OpalButton
                variant="danger"
                prominence="secondary"
                onClick={onDeleteClick}
              >
                Delete Agent
              </OpalButton>
            </InputLayouts.Horizontal>
          </Card>
        </>
      )}
    </>
  );
}
