# Agent Creation Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the agent creation page with a split-pane wizard — chat on the left, full form on the right — where the AI extracts agent fields from free-form conversation.

**Architecture:** Extract the form body from `AgentEditorPage` into a shared `AgentFormBody` component. Build a new `AgentWizardPage` that renders a chat panel + the extracted form body side-by-side inside a shared Formik context. A new streaming API route (`/api/agent-wizard-chat`) handles the LLM calls.

**Tech Stack:** Next.js 16 (App Router), React 19, Formik, TypeScript, Tailwind CSS, Server-Sent Events for streaming.

**Important codebase context:**
- The Onyx repo is at `/Users/bryantbrock/brocksoftware/meaningful-ai/onyx`
- All frontend code is in `web/src/`
- We are on branch `feature/agent-wizard` (branched from `main`)
- `AgentDescriptionParser` does NOT exist on this branch — we are building fresh
- The `components/agents/` directory does NOT exist yet — create it
- The existing `AgentEditorPage` is at `web/src/refresh-pages/AgentEditorPage.tsx` (~1624 lines)
- The create page is at `web/src/app/app/agents/create/page.tsx`
- The edit page is at `web/src/app/app/agents/edit/[id]/page.tsx`
- Existing design system uses: `SettingsLayouts`, `GeneralLayouts`, `InputLayouts`, Tailwind tokens like `bg-background`, `bg-background-subtle`, `text-text`, `text-text-muted`, `border-border`

---

### Task 1: Extract AgentFormBody from AgentEditorPage

**Files:**
- Create: `web/src/components/agents/AgentFormBody.tsx`
- Modify: `web/src/refresh-pages/AgentEditorPage.tsx`

This task extracts the form body (all form sections) into a standalone component so both the edit page and the new wizard page can reuse it.

- [ ] **Step 1: Create `AgentFormBody.tsx`**

Create `web/src/components/agents/AgentFormBody.tsx`. This component receives all needed data as props and renders the form sections. Extract lines ~1258-1612 from `AgentEditorPage.tsx` (everything inside `<SettingsLayouts.Body>` up to but not including the closing `</SettingsLayouts.Body>`).

```tsx
"use client";

import { useState } from "react";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { FullPersona } from "@/app/admin/agents/interfaces";
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
  MAX_CHARACTERS_AGENT_DESCRIPTION,
} from "@/lib/constants";
import Text from "@/refresh-components/texts/Text";
import { Card } from "@/refresh-components/cards";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import SwitchField from "@/refresh-components/form/SwitchField";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { DocumentSet } from "@/lib/types";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import {
  ProjectFile,
  UserFileStatus,
} from "@/app/app/projects/projectsService";
import {
  SvgImage,
  SvgLock,
  SvgUsers,
} from "@opal/icons";
import { Button as OpalButton } from "@opal/components";
import AgentKnowledgePane from "@/sections/knowledge/AgentKnowledgePane";
import { ValidSources } from "@/lib/types";
import * as ActionsLayouts from "@/layouts/actions-layouts";
import * as ExpandableCard from "@/layouts/expandable-card-layouts";
import { MCPServer, MCPTool, ToolSnapshot } from "@/lib/tools/interfaces";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import useFilter from "@/hooks/useFilter";
import EnabledCount from "@/refresh-components/EnabledCount";
import { SvgActions, SvgExpand, SvgFold, SvgSliders } from "@opal/icons";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";

// Re-export the sub-components that were inline in AgentEditorPage

// --- StarterMessages (was inline in AgentEditorPage) ---
function StarterMessages() {
  const max_starters = STARTER_MESSAGES_EXAMPLES.length;
  const { values } = useFormikContext<{ starter_messages: string[] }>();
  const starters = values.starter_messages || [];
  const filledStarters = starters.filter((s) => s).length;
  const canAddMore = filledStarters < max_starters;
  const visibleCount = Math.min(
    max_starters,
    Math.max(1, filledStarters === 0 ? 1 : filledStarters + (canAddMore ? 1 : 0))
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
                STARTER_MESSAGES_EXAMPLES[i] || "Enter a conversation starter..."
              }
              onRemove={() => arrayHelpers.remove(i)}
            />
          ))}
        </GeneralLayouts.Section>
      )}
    </FieldArray>
  );
}

// --- OpenApiToolCard (was inline in AgentEditorPage) ---
function OpenApiToolCard({ tool }: { tool: ToolSnapshot }) {
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

// --- MCPServerCard (was inline in AgentEditorPage) ---
interface MCPServerCardProps {
  server: MCPServer;
  tools: MCPTool[];
  isLoading: boolean;
}

function MCPServerCard({ server, tools: enabledTools, isLoading }: MCPServerCardProps) {
  const [isFolded, setIsFolded] = useState(false);
  const { values, setFieldValue, getFieldMeta } = useFormikContext<any>();
  const serverFieldName = `mcp_server_${server.id}`;
  const isServerEnabled = values[serverFieldName]?.enabled ?? false;
  const {
    query,
    setQuery,
    filtered: filteredTools,
  } = useFilter(enabledTools, (tool) => `${tool.name} ${tool.description}`);

  const enabledCount = enabledTools.filter((tool) => {
    const toolFieldValue = values[serverFieldName]?.[`tool_${tool.id}`];
    return toolFieldValue === true;
  }).length;

  return (
    <ExpandableCard.Root
      folded={isFolded}
      onFoldedChange={setIsFolded}
      defaultFolded
    >
      <ActionsLayouts.Header
        title={server.name}
        description={`${enabledTools.length} tools available`}
        icon={SvgActions}
        rightChildren={
          <div className="flex items-center gap-2">
            <EnabledCount enabled={enabledCount} total={enabledTools.length} />
            <SwitchField
              name={`${serverFieldName}.enabled`}
              onChange={(checked: boolean) => {
                if (!checked) {
                  enabledTools.forEach((tool) => {
                    setFieldValue(`${serverFieldName}.tool_${tool.id}`, false);
                  });
                }
              }}
            />
          </div>
        }
      />
      {isServerEnabled && (
        <ExpandableCard.Content>
          {enabledTools.length > 5 && (
            <div className="px-3 pt-2">
              <InputTypeIn
                placeholder="Filter tools..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
          )}
          <div className="flex flex-col gap-0.5 p-2">
            {filteredTools.map((tool) => (
              <ActionsLayouts.Header
                key={tool.id}
                title={tool.name}
                description={tool.description}
                icon={SvgActions}
                rightChildren={
                  <SwitchField name={`${serverFieldName}.tool_${tool.id}`} />
                }
              />
            ))}
          </div>
        </ExpandableCard.Content>
      )}
    </ExpandableCard.Root>
  );
}

// --- AgentIconEditor (was inline in AgentEditorPage) ---
// NOTE: This is imported from AgentEditorPage where it remains.
// We pass it as a render prop / child to AgentFormBody.

export interface AgentFormBodyProps {
  existingAgent?: FullPersona | null;
  highlightedFields?: Set<string>;

  // Data from hooks (passed down from parent)
  imageGenTool: ToolSnapshot | undefined;
  webSearchTool: ToolSnapshot | undefined;
  openURLTool: ToolSnapshot | undefined;
  codeInterpreterTool: ToolSnapshot | undefined;
  isImageGenerationAvailable: boolean;
  imageGenerationDisabledTooltip: string | undefined;
  mcpServersWithTools: { server: MCPServer; tools: MCPTool[]; isLoading: boolean }[];
  mcpServers: MCPServer[];
  openApiTools: ToolSnapshot[];
  documentSets: DocumentSet[];
  llmProviders: LLMProviderDescriptor[] | undefined;
  vectorDbEnabled: boolean;
  canUpdateFeaturedStatus: boolean;
  isPaidEnterpriseFeaturesEnabled: boolean;

  // Callbacks
  getCurrentLlm: (values: any, llmProviders: any) => string | null;
  onLlmSelect: (selected: string | null, setFieldValue: any) => void;

  // Knowledge pane callbacks
  allRecentFiles: ProjectFile[];
  onFileClick: (file: ProjectFile) => void;
  onUploadChange: (
    e: React.ChangeEvent<HTMLInputElement>,
    currentFileIds: string[],
    setFieldValue: (field: string, value: unknown) => void
  ) => void;
  hasProcessingFiles: boolean;

  // Modal triggers
  onShareClick: () => void;
  onDeleteClick?: () => void;

  // Render slots
  avatarEditor: React.ReactNode;
}

export default function AgentFormBody({
  existingAgent,
  highlightedFields,
  imageGenTool,
  webSearchTool,
  openURLTool,
  codeInterpreterTool,
  isImageGenerationAvailable,
  imageGenerationDisabledTooltip,
  mcpServersWithTools,
  mcpServers,
  openApiTools,
  documentSets,
  llmProviders,
  vectorDbEnabled,
  canUpdateFeaturedStatus,
  isPaidEnterpriseFeaturesEnabled,
  getCurrentLlm,
  onLlmSelect,
  allRecentFiles,
  onFileClick,
  onUploadChange,
  hasProcessingFiles,
  onShareClick,
  onDeleteClick,
  avatarEditor,
}: AgentFormBodyProps) {
  const { values, setFieldValue } = useFormikContext<any>();

  const isShared =
    values.is_public ||
    values.shared_user_ids?.length > 0 ||
    values.shared_group_ids?.length > 0;

  // Helper to apply highlight class
  const fieldHighlight = (fieldName: string) =>
    highlightedFields?.has(fieldName)
      ? "ring-2 ring-accent transition-all duration-500"
      : "";

  return (
    <>
      {/* General: Name + Description + Avatar */}
      <GeneralLayouts.Section flexDirection="row" gap={2.5} alignItems="start">
        <GeneralLayouts.Section>
          <InputLayouts.Vertical name="name" title="Name">
            <div className={fieldHighlight("name")}>
              <InputTypeInField name="name" placeholder="Name your agent" />
            </div>
          </InputLayouts.Vertical>

          <InputLayouts.Vertical
            name="description"
            title="Description"
            suffix="optional"
          >
            <div className={fieldHighlight("description")}>
              <InputTextAreaField
                name="description"
                placeholder="What does this agent do?"
              />
            </div>
          </InputLayouts.Vertical>
        </GeneralLayouts.Section>

        <GeneralLayouts.Section width="fit">
          <InputLayouts.Vertical name="agent_avatar" title="Agent Avatar">
            {avatarEditor}
          </InputLayouts.Vertical>
        </GeneralLayouts.Section>
      </GeneralLayouts.Section>

      <Separator noPadding />

      {/* Instructions + Starter Messages */}
      <GeneralLayouts.Section>
        <InputLayouts.Vertical
          name="instructions"
          title="Instructions"
          suffix="optional"
          description="Add instructions to tailor the response for this agent."
        >
          <div className={fieldHighlight("instructions")}>
            <InputTextAreaField
              name="instructions"
              placeholder="Think step by step and show reasoning for complex problems. Use specific examples. Emphasize action items, and leave blanks for the human to fill in when you have unknown. Use a polite enthusiastic tone."
            />
          </div>
        </InputLayouts.Vertical>

        <InputLayouts.Vertical
          name="starter_messages"
          title="Conversation Starters"
          description="Example messages that help users understand what this agent can do and how to interact with it effectively."
          suffix="optional"
        >
          <div className={fieldHighlight("starter_messages")}>
            <StarterMessages />
          </div>
        </InputLayouts.Vertical>
      </GeneralLayouts.Section>

      <Separator noPadding />

      {/* Knowledge */}
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
        onDocumentIdsChange={(ids) =>
          setFieldValue("document_ids", ids)
        }
        selectedFolderIds={values.hierarchy_node_ids}
        onFolderIdsChange={(ids) =>
          setFieldValue("hierarchy_node_ids", ids)
        }
        selectedFileIds={values.user_file_ids}
        onFileIdsChange={(ids) =>
          setFieldValue("user_file_ids", ids)
        }
        allRecentFiles={allRecentFiles}
        onFileClick={onFileClick}
        onUploadChange={(e) =>
          onUploadChange(e, values.user_file_ids, setFieldValue)
        }
        hasProcessingFiles={hasProcessingFiles}
        initialAttachedDocuments={existingAgent?.attached_documents}
        initialHierarchyNodes={existingAgent?.hierarchy_nodes}
        vectorDbEnabled={vectorDbEnabled}
      />

      <Separator noPadding />

      {/* Actions */}
      <SimpleCollapsible>
        <SimpleCollapsible.Header
          title="Actions"
          description="Tools and capabilities available for this agent to use."
        />
        <SimpleCollapsible.Content>
          <GeneralLayouts.Section gap={0.5}>
            <SimpleTooltip tooltip={imageGenerationDisabledTooltip} side="top">
              <Card variant={isImageGenerationAvailable ? undefined : "disabled"}>
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

            <Card variant={!!codeInterpreterTool ? undefined : "disabled"}>
              <InputLayouts.Horizontal
                name="code_interpreter"
                title="Code Interpreter"
                description="Generate and run code."
                disabled={!codeInterpreterTool}
              >
                <SwitchField name="code_interpreter" disabled={!codeInterpreterTool} />
              </InputLayouts.Horizontal>
            </Card>

            <>
              {(mcpServers.length > 0 || openApiTools.length > 0) && (
                <Separator noPadding className="py-1" />
              )}

              {mcpServersWithTools.length > 0 && (
                <GeneralLayouts.Section gap={0.5}>
                  {mcpServersWithTools.map(({ server, tools, isLoading }) => (
                    <MCPServerCard
                      key={server.id}
                      server={server}
                      tools={tools}
                      isLoading={isLoading}
                    />
                  ))}
                </GeneralLayouts.Section>
              )}

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

      <Separator noPadding />

      {/* Advanced Options */}
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
                description="This model will be used by default in your chats."
              >
                <LLMSelector
                  name="llm_model"
                  llmProviders={llmProviders ?? []}
                  currentLlm={getCurrentLlm(values, llmProviders)}
                  onSelect={(selected) => onLlmSelect(selected, setFieldValue)}
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
                instructions as the chat progresses. This should be brief and
                not interfere with the user messages.
              </Text>
            </GeneralLayouts.Section>
          </GeneralLayouts.Section>
        </SimpleCollapsible.Content>
      </SimpleCollapsible>

      {/* Delete button (edit only) */}
      {existingAgent && onDeleteClick && (
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
```

- [ ] **Step 2: Update `AgentEditorPage.tsx` to use `AgentFormBody`**

Replace the inline form body in `AgentEditorPage.tsx` with the new component. The file should:
1. Remove the inline `StarterMessages`, `OpenApiToolCard`, `MCPServerCard` components (they now live in `AgentFormBody.tsx`)
2. Keep `AgentIconEditor`, `FormWarningsEffect`, the Formik wrapper, hooks, modals, and `handleSubmit`
3. Replace the inline form sections (lines ~1258-1612) with `<AgentFormBody ... />`

The `AgentEditorPage` passes all hook data as props to `AgentFormBody`:

```tsx
// Inside the Formik render prop, replace the inline form body with:
<SettingsLayouts.Body>
  <AgentFormBody
    existingAgent={existingAgent}
    imageGenTool={imageGenTool}
    webSearchTool={webSearchTool}
    openURLTool={openURLTool}
    codeInterpreterTool={codeInterpreterTool}
    isImageGenerationAvailable={isImageGenerationAvailable}
    imageGenerationDisabledTooltip={imageGenerationDisabledTooltip}
    mcpServersWithTools={mcpServersWithTools}
    mcpServers={mcpServers}
    openApiTools={openApiTools}
    documentSets={documentSets ?? []}
    llmProviders={llmProviders}
    vectorDbEnabled={vectorDbEnabled}
    canUpdateFeaturedStatus={canUpdateFeaturedStatus}
    isPaidEnterpriseFeaturesEnabled={isPaidEnterpriseFeaturesEnabled}
    getCurrentLlm={getCurrentLlm}
    onLlmSelect={onLlmSelect}
    allRecentFiles={allRecentFiles}
    onFileClick={handleFileClick}
    onUploadChange={handleUploadChange}
    hasProcessingFiles={hasProcessingFiles}
    onShareClick={() => shareAgentModal.toggle(true)}
    onDeleteClick={existingAgent ? () => deleteAgentModal.toggle(true) : undefined}
    avatarEditor={<AgentIconEditor existingAgent={existingAgent} />}
  />
</SettingsLayouts.Body>
```

Remove these imports from `AgentEditorPage.tsx` (they moved to `AgentFormBody`):
- `FieldArray` (keep `Formik`, `Form`)
- `InputTypeInElementField`
- `InputDatePickerField`
- `LLMSelector`
- `STARTER_MESSAGES_EXAMPLES`, `MAX_CHARACTERS_STARTER_MESSAGE` (keep `MAX_CHARACTERS_AGENT_DESCRIPTION`)
- `Card`
- `SimpleCollapsible`
- `SwitchField`
- `SimpleTooltip`
- `Text`
- `AgentKnowledgePane`
- `ActionsLayouts`, `ExpandableCard`
- `InputTypeIn`
- `useFilter`
- `EnabledCount`

Add import:
```tsx
import AgentFormBody from "@/components/agents/AgentFormBody";
```

- [ ] **Step 3: Verify the edit flow still works**

Run: `cd /Users/bryantbrock/brocksoftware/meaningful-ai/onyx && npm run --prefix web build 2>&1 | tail -20`
Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
cd /Users/bryantbrock/brocksoftware/meaningful-ai/onyx
git add web/src/components/agents/AgentFormBody.tsx web/src/refresh-pages/AgentEditorPage.tsx
git commit -m "refactor: extract AgentFormBody from AgentEditorPage for reuse"
```

---

### Task 2: Create the streaming API endpoint

**Files:**
- Create: `web/src/app/api/agent-wizard-chat/route.ts`

- [ ] **Step 1: Create the endpoint**

Create `web/src/app/api/agent-wizard-chat/route.ts`:

```typescript
import { NextRequest } from "next/server";

const SYSTEM_PROMPT = `You are an AI assistant that helps users create agents (AI assistants) through natural conversation. Your job is to understand what the user wants their agent to do, and extract structured configuration from the conversation.

Respond conversationally — confirm what you understood, suggest improvements, and ask natural follow-up questions. Be helpful and concise.

After your conversational response, you MUST include a structured field update block. This block is delimited by <<<FIELDS>>> and <<<END>>> markers. It contains a JSON object with the agent fields you want to set or update based on the conversation so far.

Available fields:
- name (string): Short name for the agent (2-5 words)
- description (string): One-sentence description, max 300 chars
- instructions (string): Detailed system prompt defining behavior, tone, constraints
- starter_messages (string[]): 3-5 example messages users might send, each max 200 chars
- web_search (boolean): Whether the agent needs web search
- image_generation (boolean): Whether the agent needs image generation
- code_interpreter (boolean): Whether the agent needs to run code

Rules:
- Only include fields that should change. If a field is already set correctly (check currentValues), do not include it.
- The <<<FIELDS>>>...<<<END>>> block must be valid JSON.
- If it's the first message, try to fill in as many fields as you can from the user's description.
- Naturally guide the user toward filling important fields (instructions, starters) but don't be rigid.
- If the user asks to change something specific, update only that field.

Example response format:
Great, I've set up a quality control assistant! I wrote instructions focused on defect identification and root cause analysis. I also added some conversation starters your team might use.

Want to attach any knowledge sources like your ISO documentation? You can also tweak anything on the form to the right.

<<<FIELDS>>>
{"name": "Quality Control Assistant", "instructions": "You are a manufacturing quality control assistant..."}
<<<END>>>`;

export async function POST(req: NextRequest) {
  try {
    const { messages, currentValues } = await req.json();

    if (!messages || !Array.isArray(messages) || messages.length === 0) {
      return new Response(
        JSON.stringify({ error: "Messages are required" }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    // Forward cookies to backend for auth
    const cookie = req.headers.get("cookie") || "";
    const backendUrl = process.env.INTERNAL_URL || "http://api_server:8080";

    // Get LLM providers from backend
    const providersRes = await fetch(`${backendUrl}/admin/llm/provider`, {
      headers: { cookie },
    });

    if (!providersRes.ok) {
      return new Response(
        JSON.stringify({ error: "Failed to fetch LLM providers" }),
        { status: 500, headers: { "Content-Type": "application/json" } }
      );
    }

    const providers = await providersRes.json();
    if (!providers?.length) {
      return new Response(
        JSON.stringify({ error: "No LLM providers configured" }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    // Find provider — prefer OpenAI for speed, fall back to default or first
    const openaiProvider = providers.find(
      (p: any) => p.provider?.toLowerCase() === "openai"
    );
    const defaultProvider =
      openaiProvider ||
      providers.find((p: any) => p.is_default_provider) ||
      providers[0];

    const providerType = defaultProvider.provider?.toLowerCase();
    const apiKey = defaultProvider.api_key;
    const model =
      defaultProvider.default_model_name ||
      defaultProvider.fast_default_model_name;

    if (!apiKey || !model) {
      return new Response(
        JSON.stringify({ error: "Provider missing API key or model" }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    // Build the augmented system prompt with current form values
    const augmentedSystem = `${SYSTEM_PROMPT}\n\nCurrent agent form values:\n${JSON.stringify(currentValues || {}, null, 2)}`;

    // Build messages array for the LLM
    const llmMessages = messages.map((m: { role: string; content: string }) => ({
      role: m.role,
      content: m.content,
    }));

    // Stream the response
    if (providerType === "openai") {
      const res = await fetch("https://api.openai.com/v1/chat/completions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          model,
          messages: [
            { role: "system", content: augmentedSystem },
            ...llmMessages,
          ],
          temperature: 0.4,
          stream: true,
        }),
      });

      if (!res.ok) {
        const err = await res.text();
        console.error("OpenAI error:", err);
        return new Response(
          JSON.stringify({ error: "LLM call failed" }),
          { status: 500, headers: { "Content-Type": "application/json" } }
        );
      }

      // Forward the SSE stream
      return new Response(res.body, {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
        },
      });
    } else if (providerType === "anthropic") {
      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": apiKey,
          "anthropic-version": "2023-06-01",
        },
        body: JSON.stringify({
          model,
          max_tokens: 2048,
          system: augmentedSystem,
          messages: llmMessages,
          stream: true,
        }),
      });

      if (!res.ok) {
        const err = await res.text();
        console.error("Anthropic error:", err);
        return new Response(
          JSON.stringify({ error: "LLM call failed" }),
          { status: 500, headers: { "Content-Type": "application/json" } }
        );
      }

      // Forward the SSE stream
      return new Response(res.body, {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
        },
      });
    } else {
      return new Response(
        JSON.stringify({ error: `Unsupported provider: ${providerType}` }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }
  } catch (error) {
    console.error("Agent wizard chat error:", error);
    return new Response(
      JSON.stringify({ error: "Internal server error" }),
      { status: 500, headers: { "Content-Type": "application/json" } }
    );
  }
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd /Users/bryantbrock/brocksoftware/meaningful-ai/onyx && npx --prefix web tsc --noEmit --project web/tsconfig.json 2>&1 | tail -20`
Expected: No errors from the new file.

- [ ] **Step 3: Commit**

```bash
cd /Users/bryantbrock/brocksoftware/meaningful-ai/onyx
git add web/src/app/api/agent-wizard-chat/route.ts
git commit -m "feat: add streaming API endpoint for agent wizard chat"
```

---

### Task 3: Create AgentBuilderChat component

**Files:**
- Create: `web/src/components/agents/AgentBuilderChat.tsx`

- [ ] **Step 1: Create the chat component**

Create `web/src/components/agents/AgentBuilderChat.tsx`:

```tsx
"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useFormikContext } from "formik";
import { SvgArrowUp } from "@opal/icons";
import { Button } from "@opal/components";

interface ChatMessage {
  role: "assistant" | "user";
  content: string;
}

const WELCOME_MESSAGE: ChatMessage = {
  role: "assistant",
  content:
    "Tell me about the agent you want to create. What should it do? Who is it for?",
};

interface AgentBuilderChatProps {
  onFieldsUpdated?: (fieldNames: string[]) => void;
}

export default function AgentBuilderChat({
  onFieldsUpdated,
}: AgentBuilderChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MESSAGE]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const { values, setFieldValue, setFieldTouched } = useFormikContext<any>();

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setInput(e.target.value);
      e.target.style.height = "auto";
      e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
    },
    []
  );

  // Parse the <<<FIELDS>>> block from the AI response and apply to form
  const applyFieldUpdates = useCallback(
    (fullResponse: string): string => {
      const fieldsMatch = fullResponse.match(
        /<<<FIELDS>>>([\s\S]*?)<<<END>>>/
      );
      if (!fieldsMatch) return fullResponse;

      // Strip the fields block from displayed text
      const displayText = fullResponse
        .replace(/<<<FIELDS>>>[\s\S]*?<<<END>>>/, "")
        .trim();

      try {
        const updates = JSON.parse(fieldsMatch[1]);
        const updatedFieldNames: string[] = [];

        Object.entries(updates).forEach(([key, value]) => {
          setFieldValue(key, value);
          setFieldTouched(key, true, false);
          updatedFieldNames.push(key);
        });

        if (onFieldsUpdated && updatedFieldNames.length > 0) {
          onFieldsUpdated(updatedFieldNames);
        }
      } catch (err) {
        console.error("Failed to parse field updates:", err);
      }

      return displayText;
    },
    [setFieldValue, setFieldTouched, onFieldsUpdated]
  );

  // Parse SSE stream chunks based on provider format
  const parseSSEChunk = useCallback(
    (line: string): string => {
      if (!line.startsWith("data: ")) return "";
      const data = line.slice(6);
      if (data === "[DONE]") return "";

      try {
        const parsed = JSON.parse(data);

        // OpenAI format
        if (parsed.choices?.[0]?.delta?.content) {
          return parsed.choices[0].delta.content;
        }

        // Anthropic format
        if (parsed.type === "content_block_delta" && parsed.delta?.text) {
          return parsed.delta.text;
        }
      } catch {
        // Not JSON or unparseable — skip
      }
      return "";
    },
    []
  );

  async function handleSend() {
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;

    const userMessage: ChatMessage = { role: "user", content: trimmed };
    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    setInput("");
    setIsStreaming(true);

    // Reset textarea height
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
    }

    // Gather current form values to send to API
    const currentValues = {
      name: values.name || "",
      description: values.description || "",
      instructions: values.instructions || "",
      starter_messages: (values.starter_messages || []).filter(
        (s: string) => s
      ),
      web_search: values.web_search || false,
      image_generation: values.image_generation || false,
      code_interpreter: values.code_interpreter || false,
    };

    try {
      const res = await fetch("/api/agent-wizard-chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: newMessages.filter((m) => m !== WELCOME_MESSAGE),
          currentValues,
        }),
      });

      if (!res.ok) {
        const error = await res.json().catch(() => ({ error: "Request failed" }));
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: `Sorry, something went wrong: ${error.error || "Unknown error"}. You can still fill in the form directly.`,
          },
        ]);
        setIsStreaming(false);
        return;
      }

      // Read SSE stream
      const reader = res.body?.getReader();
      if (!reader) {
        setIsStreaming(false);
        return;
      }

      const decoder = new TextDecoder();
      let fullResponse = "";
      let buffer = "";

      // Add placeholder assistant message
      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || ""; // Keep incomplete line in buffer

        for (const line of lines) {
          const text = parseSSEChunk(line);
          if (text) {
            fullResponse += text;
            // Update the last message with accumulated text (strip fields block for display)
            const displayText = fullResponse
              .replace(/<<<FIELDS>>>[\s\S]*$/, "")
              .trim();
            setMessages((prev) => {
              const updated = [...prev];
              updated[updated.length - 1] = {
                role: "assistant",
                content: displayText,
              };
              return updated;
            });
          }
        }
      }

      // Process remaining buffer
      if (buffer) {
        const text = parseSSEChunk(buffer);
        if (text) fullResponse += text;
      }

      // Parse fields and get clean display text
      const finalDisplayText = applyFieldUpdates(fullResponse);
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          content: finalDisplayText,
        };
        return updated;
      });
    } catch (err) {
      console.error("Chat error:", err);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            "Sorry, I couldn't connect. You can still fill in the form directly.",
        },
      ]);
    } finally {
      setIsStreaming(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="flex flex-col h-full border-r border-border">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
        <div className="w-7 h-7 rounded-full bg-accent flex items-center justify-center">
          <span className="text-white text-xs font-bold">AI</span>
        </div>
        <div>
          <div className="text-sm font-semibold text-text">Agent Builder</div>
          <div className="text-xs text-text-muted">
            Describe your agent and I&apos;ll set it up
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            {msg.role === "assistant" && (
              <div className="w-6 h-6 rounded-full bg-accent flex-shrink-0 flex items-center justify-center mr-2 mt-0.5">
                <span className="text-white text-[10px] font-bold">AI</span>
              </div>
            )}
            <div
              className={`max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-background-emphasis text-text"
                  : "bg-background-subtle text-text"
              }`}
            >
              {msg.content || (
                <span className="inline-flex gap-1">
                  <span className="animate-bounce text-text-muted">.</span>
                  <span className="animate-bounce text-text-muted" style={{ animationDelay: "0.1s" }}>.</span>
                  <span className="animate-bounce text-text-muted" style={{ animationDelay: "0.2s" }}>.</span>
                </span>
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-border">
        <div className="flex items-end gap-2 bg-background-subtle rounded-lg border border-border px-3 py-2 focus-within:ring-2 focus-within:ring-accent">
          <textarea
            ref={inputRef}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder="Describe your agent..."
            disabled={isStreaming}
            rows={1}
            className="flex-1 bg-transparent text-sm text-text placeholder-text-muted resize-none outline-none max-h-[120px]"
          />
          <button
            onClick={handleSend}
            disabled={isStreaming || !input.trim()}
            className="w-7 h-7 rounded-md bg-accent text-white flex items-center justify-center flex-shrink-0 disabled:opacity-40 hover:opacity-90 transition-opacity"
          >
            <SvgArrowUp className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd /Users/bryantbrock/brocksoftware/meaningful-ai/onyx && npx --prefix web tsc --noEmit --project web/tsconfig.json 2>&1 | tail -20`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/bryantbrock/brocksoftware/meaningful-ai/onyx
git add web/src/components/agents/AgentBuilderChat.tsx
git commit -m "feat: add AgentBuilderChat component with streaming support"
```

---

### Task 4: Create AgentWizardPage and wire up routing

**Files:**
- Create: `web/src/refresh-pages/AgentWizardPage.tsx`
- Modify: `web/src/app/app/agents/create/page.tsx`

- [ ] **Step 1: Create `AgentWizardPage.tsx`**

Create `web/src/refresh-pages/AgentWizardPage.tsx`. This is the split-pane page that wraps the chat and form in a shared Formik context. It reuses all the same hooks, initialValues, validationSchema, and handleSubmit logic from `AgentEditorPage` — essentially a copy of the Formik setup with a different layout.

```tsx
"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { Button as OpalButton } from "@opal/components";
import { Hoverable } from "@opal/core";
import { FullPersona } from "@/app/admin/agents/interfaces";
import { buildImgUrl } from "@/app/app/components/files/images/utils";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { useFormikContext } from "formik";
import { parseLlmDescriptor, structureValue } from "@/lib/llmConfig/utils";
import { useLLMProviders } from "@/hooks/useLLMProviders";
import {
  STARTER_MESSAGES_EXAMPLES,
  MAX_CHARACTERS_STARTER_MESSAGE,
  MAX_CHARACTERS_AGENT_DESCRIPTION,
} from "@/lib/constants";
import {
  IMAGE_GENERATION_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
  PYTHON_TOOL_ID,
  SEARCH_TOOL_ID,
  OPEN_URL_TOOL_ID,
} from "@/app/app/components/tools/constants";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { useDocumentSets } from "@/app/admin/documents/sets/hooks";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { toast } from "@/hooks/useToast";
import UserFilesModal from "@/components/modals/UserFilesModal";
import {
  ProjectFile,
  UserFileStatus,
} from "@/app/app/projects/projectsService";
import {
  SvgOnyxOctagon,
} from "@opal/icons";
import CustomAgentAvatar, {
  agentAvatarIconMap,
} from "@/refresh-components/avatars/CustomAgentAvatar";
import InputAvatar from "@/refresh-components/inputs/InputAvatar";
import Button from "@/refresh-components/buttons/Button";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import SquareButton from "@/refresh-components/buttons/SquareButton";
import { SvgImage } from "@opal/icons";
import { useAgents } from "@/hooks/useAgents";
import {
  createPersona,
  PersonaUpsertParameters,
} from "@/app/admin/agents/lib";
import useMcpServersForAgentEditor from "@/hooks/useMcpServersForAgentEditor";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import { useAvailableTools } from "@/hooks/useAvailableTools";
import { MCPTool } from "@/lib/tools/interfaces";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { useAppRouter } from "@/hooks/appNavigation";
import { isDateInFuture } from "@/lib/dateUtils";
import ShareAgentModal from "@/sections/modals/ShareAgentModal";
import { ValidSources } from "@/lib/types";
import { useVectorDbEnabled } from "@/providers/SettingsProvider";
import { useUser } from "@/providers/UserProvider";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import AgentFormBody from "@/components/agents/AgentFormBody";
import AgentBuilderChat from "@/components/agents/AgentBuilderChat";

// FormWarningsEffect — same as in AgentEditorPage
function FormWarningsEffect() {
  const { values, setStatus } = useFormikContext<{
    web_search: boolean;
    open_url: boolean;
  }>();

  useEffect(() => {
    const warnings: Record<string, string> = {};
    if (values.web_search && !values.open_url) {
      warnings.open_url =
        "Web Search without the ability to open URLs can lead to significantly worse web based results.";
    }
    setStatus({ warnings });
  }, [values.web_search, values.open_url, setStatus]);

  return null;
}

// AgentIconEditor — same as in AgentEditorPage
function AgentIconEditor() {
  const { values, setFieldValue } = useFormikContext<{
    name: string;
    icon_name: string | null;
    uploaded_image_id: string | null;
    remove_image: boolean | null;
  }>();
  const [uploadedImagePreview, setUploadedImagePreview] = useState<string | null>(null);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function handleImageUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadedImagePreview(null);
    setFieldValue("icon_name", null);
    setFieldValue("remove_image", false);
    const reader = new FileReader();
    reader.onloadend = () => setUploadedImagePreview(reader.result as string);
    reader.readAsDataURL(file);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetch("/api/admin/persona/upload-image", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        setUploadedImagePreview(null);
        return;
      }
      const { file_id } = await response.json();
      setFieldValue("uploaded_image_id", file_id);
      setPopoverOpen(false);
    } catch {
      setUploadedImagePreview(null);
    }
  }

  const imageSrc = uploadedImagePreview
    ? uploadedImagePreview
    : values.uploaded_image_id
      ? buildImgUrl(values.uploaded_image_id)
      : undefined;

  function handleIconClick(iconName: string | null) {
    setFieldValue("icon_name", iconName);
    setFieldValue("uploaded_image_id", null);
    setFieldValue("remove_image", true);
    setUploadedImagePreview(null);
    setPopoverOpen(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  return (
    <>
      <input ref={fileInputRef} type="file" accept="image/*" onChange={handleImageUpload} className="hidden" />
      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <Popover.Trigger asChild>
          <Hoverable.Root group="inputAvatar" widthVariant="fit">
            <InputAvatar className="relative flex flex-col items-center justify-center h-[7.5rem] w-[7.5rem]">
              <CustomAgentAvatar
                size={imageSrc ? 7.5 * 16 : 40}
                src={imageSrc}
                iconName={values.icon_name ?? undefined}
                name={values.name}
              />
              <div className="absolute bottom-0 left-1/2 -translate-x-1/2 mb-2">
                <Hoverable.Item group="inputAvatar" variant="opacity-on-hover">
                  <Button className="h-[1.75rem]" secondary>Edit</Button>
                </Hoverable.Item>
              </div>
            </InputAvatar>
          </Hoverable.Root>
        </Popover.Trigger>
        <Popover.Content>
          <PopoverMenu>
            {[
              <LineItem key="upload-image" icon={SvgImage} onClick={() => fileInputRef.current?.click()} emphasized>
                Upload Image
              </LineItem>,
              null,
              <div className="grid grid-cols-4 gap-1" key="icon-grid">
                <SquareButton
                  key="default-icon"
                  icon={() => <CustomAgentAvatar name={values.name} size={30} />}
                  onClick={() => handleIconClick(null)}
                  transient={!imageSrc && values.icon_name === null}
                />
                {Object.keys(agentAvatarIconMap).map((iconName) => (
                  <SquareButton
                    key={iconName}
                    onClick={() => handleIconClick(iconName)}
                    icon={() => <CustomAgentAvatar iconName={iconName} size={30} />}
                    transient={values.icon_name === iconName}
                  />
                ))}
              </div>,
            ]}
          </PopoverMenu>
        </Popover.Content>
      </Popover>
    </>
  );
}

export default function AgentWizardPage() {
  const router = useRouter();
  const appRouter = useAppRouter();
  const { refresh: refreshAgents } = useAgents();
  const shareAgentModal = useCreateModal();
  const { isAdmin, isCurator } = useUser();
  const canUpdateFeaturedStatus = isAdmin || isCurator;
  const vectorDbEnabled = useVectorDbEnabled();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  // Track highlighted fields (recently updated by chat)
  const [highlightedFields, setHighlightedFields] = useState<Set<string>>(new Set());

  const handleFieldsUpdated = useCallback((fieldNames: string[]) => {
    setHighlightedFields(new Set(fieldNames));
    setTimeout(() => setHighlightedFields(new Set()), 2000);
  }, []);

  // LLM Model Selection
  const getCurrentLlm = useCallback(
    (values: any, llmProviders: any) =>
      values.llm_model_version_override && values.llm_model_provider_override
        ? (() => {
            const provider = llmProviders?.find(
              (p: any) => p.name === values.llm_model_provider_override
            );
            return structureValue(
              values.llm_model_provider_override,
              provider?.provider || "",
              values.llm_model_version_override
            );
          })()
        : null,
    []
  );

  const onLlmSelect = useCallback(
    (selected: string | null, setFieldValue: any) => {
      if (selected === null) {
        setFieldValue("llm_model_version_override", null);
        setFieldValue("llm_model_provider_override", null);
      } else {
        const { modelName, name } = parseLlmDescriptor(selected);
        if (modelName && name) {
          setFieldValue("llm_model_version_override", modelName);
          setFieldValue("llm_model_provider_override", name);
        }
      }
    },
    []
  );

  // Data hooks
  const { allRecentFiles, beginUpload } = useProjectsContext();
  const { data: documentSets } = useDocumentSets();
  const userFilesModal = useCreateModal();
  const [presentingDocument, setPresentingDocument] = useState<{
    document_id: string;
    semantic_identifier: string;
  } | null>(null);

  const { mcpData, isLoading: isMcpLoading } = useMcpServersForAgentEditor();
  const { openApiTools: openApiToolsRaw, isLoading: isOpenApiLoading } = useOpenApiTools();
  const { llmProviders } = useLLMProviders();
  const mcpServers = mcpData?.mcp_servers ?? [];
  const openApiTools = openApiToolsRaw ?? [];

  const { tools: availableTools, isLoading: isToolsLoading } = useAvailableTools();
  const searchTool = availableTools?.find((t) => t.in_code_tool_id === SEARCH_TOOL_ID);
  const imageGenTool = availableTools?.find((t) => t.in_code_tool_id === IMAGE_GENERATION_TOOL_ID);
  const webSearchTool = availableTools?.find((t) => t.in_code_tool_id === WEB_SEARCH_TOOL_ID);
  const openURLTool = availableTools?.find((t) => t.in_code_tool_id === OPEN_URL_TOOL_ID);
  const codeInterpreterTool = availableTools?.find((t) => t.in_code_tool_id === PYTHON_TOOL_ID);
  const isImageGenerationAvailable = !!imageGenTool;
  const imageGenerationDisabledTooltip = isImageGenerationAvailable
    ? undefined
    : "Image generation requires a configured model. If you have access, set one up under Settings > Image Generation, or ask an admin.";

  const mcpServersWithTools = mcpServers.map((server) => {
    const serverTools: MCPTool[] = (availableTools || [])
      .filter((tool) => tool.mcp_server_id === server.id)
      .map((tool) => ({
        id: tool.id.toString(),
        icon: getActionIcon(server.server_url, server.name),
        name: tool.display_name || tool.name,
        description: tool.description,
        isAvailable: true,
        isEnabled: tool.enabled,
      }));
    return { server, tools: serverTools, isLoading: false };
  });

  // Initial values — same as AgentEditorPage but for new agents only
  const initialValues = {
    icon_name: null as string | null,
    uploaded_image_id: null as string | null,
    remove_image: false,
    name: "",
    description: "",
    instructions: "",
    starter_messages: Array.from({ length: STARTER_MESSAGES_EXAMPLES.length }, () => ""),
    enable_knowledge: false,
    document_set_ids: [] as number[],
    document_ids: [] as string[],
    hierarchy_node_ids: [] as number[],
    user_file_ids: [] as string[],
    selected_sources: [] as ValidSources[],
    llm_model_provider_override: null as string | null,
    llm_model_version_override: null as string | null,
    knowledge_cutoff_date: null as Date | null,
    replace_base_system_prompt: false,
    reminders: "",
    image_generation: false,
    web_search: false,
    open_url: false,
    code_interpreter: false,
    ...Object.fromEntries(
      mcpServersWithTools.map(({ server, tools }) => {
        const toolFields: Record<string, boolean> = {};
        tools.forEach((tool) => { toolFields[`tool_${tool.id}`] = false; });
        return [`mcp_server_${server.id}`, { enabled: false, ...toolFields }];
      })
    ),
    ...Object.fromEntries(
      openApiTools.map((t) => [`openapi_tool_${t.id}`, false])
    ),
    shared_user_ids: [] as string[],
    shared_group_ids: [] as number[],
    is_public: false,
    label_ids: [] as number[],
    is_featured: false,
  };

  // Validation — same as AgentEditorPage
  const validationSchema = Yup.object().shape({
    icon_name: Yup.string().nullable(),
    remove_image: Yup.boolean().optional(),
    uploaded_image_id: Yup.string().nullable(),
    name: Yup.string().required("Agent name is required."),
    description: Yup.string()
      .max(MAX_CHARACTERS_AGENT_DESCRIPTION, `Description must be ${MAX_CHARACTERS_AGENT_DESCRIPTION} characters or less`)
      .optional(),
    instructions: Yup.string().optional(),
    starter_messages: Yup.array().of(
      Yup.string().max(MAX_CHARACTERS_STARTER_MESSAGE, `Conversation starter must be ${MAX_CHARACTERS_STARTER_MESSAGE} characters or less`)
    ),
    enable_knowledge: Yup.boolean(),
    document_set_ids: Yup.array().of(Yup.number()),
    document_ids: Yup.array().of(Yup.string()),
    hierarchy_node_ids: Yup.array().of(Yup.number()),
    user_file_ids: Yup.array().of(Yup.string()),
    selected_sources: Yup.array().of(Yup.string()),
    llm_model_provider_override: Yup.string().nullable().optional(),
    llm_model_version_override: Yup.string().nullable().optional(),
    knowledge_cutoff_date: Yup.date()
      .nullable()
      .optional()
      .test("knowledge-cutoff-date-not-in-future", "Knowledge cutoff date must be today or earlier.", (value) => !value || !isDateInFuture(value)),
    replace_base_system_prompt: Yup.boolean(),
    reminders: Yup.string().optional(),
    ...Object.fromEntries(mcpServers.map((server) => [`mcp_server_${server.id}`, Yup.object()])),
    ...Object.fromEntries(openApiTools.map((t) => [`openapi_tool_${t.id}`, Yup.boolean()])),
  });

  // Submit handler — same as AgentEditorPage (create only, no update path)
  async function handleSubmit(values: typeof initialValues) {
    try {
      const starterMessages = values.starter_messages
        .filter((message: string) => message.trim() !== "")
        .map((message: string) => ({ message, name: message }));
      const finalStarterMessages = starterMessages.length > 0 ? starterMessages : null;

      const toolIds: number[] = [];
      if (values.enable_knowledge && vectorDbEnabled && searchTool) toolIds.push(searchTool.id);
      if (values.image_generation && imageGenTool) toolIds.push(imageGenTool.id);
      if (values.web_search && webSearchTool) toolIds.push(webSearchTool.id);
      if (values.open_url && openURLTool) toolIds.push(openURLTool.id);
      if (values.code_interpreter && codeInterpreterTool) toolIds.push(codeInterpreterTool.id);

      mcpServers.forEach((server) => {
        const serverData = (values as any)[`mcp_server_${server.id}`];
        if (serverData?.enabled) {
          Object.keys(serverData).forEach((key) => {
            if (key.startsWith("tool_") && serverData[key] === true) {
              const toolId = parseInt(key.replace("tool_", ""), 10);
              if (!isNaN(toolId)) toolIds.push(toolId);
            }
          });
        }
      });

      openApiTools.forEach((t) => {
        if ((values as any)[`openapi_tool_${t.id}`] === true) toolIds.push(t.id);
      });

      const submissionData: PersonaUpsertParameters = {
        name: values.name,
        description: values.description,
        document_set_ids: values.enable_knowledge ? values.document_set_ids : [],
        is_public: values.is_public,
        llm_model_provider_override: values.llm_model_provider_override || null,
        llm_model_version_override: values.llm_model_version_override || null,
        starter_messages: finalStarterMessages,
        users: values.shared_user_ids,
        groups: values.shared_group_ids,
        tool_ids: toolIds,
        remove_image: values.remove_image ?? false,
        uploaded_image_id: values.uploaded_image_id,
        icon_name: values.icon_name,
        search_start_date: values.knowledge_cutoff_date || null,
        label_ids: values.label_ids,
        is_featured: values.is_featured,
        user_file_ids: values.enable_knowledge ? values.user_file_ids : [],
        hierarchy_node_ids: values.enable_knowledge ? values.hierarchy_node_ids : [],
        document_ids: values.enable_knowledge ? values.document_ids : [],
        system_prompt: values.instructions,
        replace_base_system_prompt: values.replace_base_system_prompt,
        task_prompt: values.reminders || "",
        datetime_aware: false,
      };

      const personaResponse = await createPersona(submissionData);

      if (!personaResponse || !personaResponse.ok) {
        const error = personaResponse ? await personaResponse.text() : "No response received";
        toast.error(`Failed to create agent - ${error}`);
        return;
      }

      const agent = await personaResponse.json();
      toast.success(`Agent "${agent.name}" created successfully`);
      await refreshAgents();
      appRouter({ agentId: agent.id });
    } catch (error) {
      console.error("Submit error:", error);
      toast.error(`An error occurred: ${error}`);
    }
  }

  // File handlers for knowledge pane
  function handleFileClick(file: ProjectFile) {
    setPresentingDocument({
      document_id: `project_file__${file.file_id}`,
      semantic_identifier: file.name,
    });
  }

  async function handleUploadChange(
    e: React.ChangeEvent<HTMLInputElement>,
    currentFileIds: string[],
    setFieldValue: (field: string, value: unknown) => void
  ) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    try {
      let selectedIds = [...(currentFileIds || [])];
      const optimistic = await beginUpload(Array.from(files), null, (result) => {
        const uploadedFiles = result.user_files || [];
        if (uploadedFiles.length === 0) return;
        const tempToFinal = new Map(
          uploadedFiles.filter((f) => f.temp_id).map((f) => [f.temp_id as string, f.id])
        );
        const replaced = (selectedIds || []).map((id: string) => tempToFinal.get(id) ?? id);
        selectedIds = replaced;
        setFieldValue("user_file_ids", replaced);
      });
      if (optimistic) {
        const optimisticIds = optimistic.map((f) => f.id);
        selectedIds = [...selectedIds, ...optimisticIds];
        setFieldValue("user_file_ids", selectedIds);
      }
    } catch (error) {
      console.error("Upload error:", error);
    }
  }

  // Wait for tools to load
  if (isToolsLoading || isMcpLoading || isOpenApiLoading) {
    return null;
  }

  return (
    <div className="h-full w-full flex flex-col">
      <Formik
        initialValues={initialValues}
        validationSchema={validationSchema}
        onSubmit={handleSubmit}
        validateOnChange
        validateOnBlur
        validateOnMount
      >
        {({ isSubmitting, isValid, dirty, values, setFieldValue }) => {
          const fileStatusMap = new Map(allRecentFiles.map((f) => [f.id, f.status]));
          const hasUploadingFiles = values.user_file_ids.some((fileId: string) => {
            const status = fileStatusMap.get(fileId);
            return status === undefined ? fileId.startsWith("temp_") : status === UserFileStatus.UPLOADING;
          });
          const hasProcessingFiles = values.user_file_ids.some(
            (fileId: string) => fileStatusMap.get(fileId) === UserFileStatus.PROCESSING
          );

          return (
            <>
              <FormWarningsEffect />

              <shareAgentModal.Provider>
                <ShareAgentModal
                  userIds={values.shared_user_ids}
                  groupIds={values.shared_group_ids}
                  isPublic={values.is_public}
                  isFeatured={values.is_featured}
                  labelIds={values.label_ids}
                  onShare={async (userIds, groupIds, isPublic, isFeatured, labelIds) => {
                    setFieldValue("shared_user_ids", userIds);
                    setFieldValue("shared_group_ids", groupIds);
                    setFieldValue("is_public", isPublic);
                    setFieldValue("is_featured", isFeatured);
                    setFieldValue("label_ids", labelIds);
                    shareAgentModal.toggle(false);
                  }}
                />
              </shareAgentModal.Provider>

              <Form className="h-full w-full flex">
                {/* Left: Chat Panel */}
                <div className="w-[40%] min-w-[320px] h-full">
                  <AgentBuilderChat onFieldsUpdated={handleFieldsUpdated} />
                </div>

                {/* Right: Form Panel */}
                <div className="w-[60%] h-full flex flex-col overflow-hidden">
                  {/* Sticky header with Cancel + Create */}
                  <div className="flex items-center justify-between px-5 py-3 border-b border-border flex-shrink-0">
                    <div className="text-sm font-semibold text-text">
                      Agent Configuration
                    </div>
                    <div className="flex gap-2">
                      <OpalButton
                        prominence="secondary"
                        type="button"
                        onClick={() => router.back()}
                      >
                        Cancel
                      </OpalButton>
                      <SimpleTooltip
                        tooltip={
                          isSubmitting
                            ? "Creating agent..."
                            : !isValid
                              ? "Please fix the errors in the form before saving."
                              : !dirty
                                ? "Describe your agent in the chat or fill in the form."
                                : hasUploadingFiles
                                  ? "Please wait for files to finish uploading."
                                  : undefined
                        }
                        side="bottom"
                      >
                        <OpalButton
                          disabled={isSubmitting || !isValid || !dirty || hasUploadingFiles}
                          type="submit"
                        >
                          Create Agent
                        </OpalButton>
                      </SimpleTooltip>
                    </div>
                  </div>

                  {/* Scrollable form body */}
                  <div className="flex-1 overflow-y-auto p-5">
                    <div className="max-w-[var(--container-md)] mx-auto flex flex-col gap-5">
                      <AgentFormBody
                        highlightedFields={highlightedFields}
                        imageGenTool={imageGenTool}
                        webSearchTool={webSearchTool}
                        openURLTool={openURLTool}
                        codeInterpreterTool={codeInterpreterTool}
                        isImageGenerationAvailable={isImageGenerationAvailable}
                        imageGenerationDisabledTooltip={imageGenerationDisabledTooltip}
                        mcpServersWithTools={mcpServersWithTools}
                        mcpServers={mcpServers}
                        openApiTools={openApiTools}
                        documentSets={documentSets ?? []}
                        llmProviders={llmProviders}
                        vectorDbEnabled={vectorDbEnabled}
                        canUpdateFeaturedStatus={canUpdateFeaturedStatus}
                        isPaidEnterpriseFeaturesEnabled={isPaidEnterpriseFeaturesEnabled}
                        getCurrentLlm={getCurrentLlm}
                        onLlmSelect={onLlmSelect}
                        allRecentFiles={allRecentFiles}
                        onFileClick={handleFileClick}
                        onUploadChange={handleUploadChange}
                        hasProcessingFiles={hasProcessingFiles}
                        onShareClick={() => shareAgentModal.toggle(true)}
                        avatarEditor={<AgentIconEditor />}
                      />
                    </div>
                  </div>
                </div>
              </Form>
            </>
          );
        }}
      </Formik>
    </div>
  );
}
```

- [ ] **Step 2: Update the create page route**

Modify `web/src/app/app/agents/create/page.tsx`:

```tsx
import AgentWizardPage from "@/refresh-pages/AgentWizardPage";
import * as AppLayouts from "@/layouts/app-layouts";

export default async function Page() {
  return (
    <AppLayouts.Root>
      <AgentWizardPage />
    </AppLayouts.Root>
  );
}
```

- [ ] **Step 3: Verify it builds**

Run: `cd /Users/bryantbrock/brocksoftware/meaningful-ai/onyx && npm run --prefix web build 2>&1 | tail -30`
Expected: Build succeeds. The create page now renders the wizard.

- [ ] **Step 4: Commit**

```bash
cd /Users/bryantbrock/brocksoftware/meaningful-ai/onyx
git add web/src/refresh-pages/AgentWizardPage.tsx web/src/app/app/agents/create/page.tsx
git commit -m "feat: add AgentWizardPage and wire up create route"
```

---

### Task 5: Build verification and cleanup

**Files:**
- Verify: all new and modified files

- [ ] **Step 1: Full build check**

Run: `cd /Users/bryantbrock/brocksoftware/meaningful-ai/onyx && npm run --prefix web build 2>&1 | tail -30`
Expected: Build succeeds with no errors.

- [ ] **Step 2: Verify the edit flow is unchanged**

Check that the edit page still imports and uses `AgentEditorPage`:

Run: `cd /Users/bryantbrock/brocksoftware/meaningful-ai/onyx && grep -n "AgentEditorPage" web/src/app/app/agents/edit/\[id\]/page.tsx`
Expected: Shows the import line — unchanged from before.

- [ ] **Step 3: Verify file structure**

Run: `cd /Users/bryantbrock/brocksoftware/meaningful-ai/onyx && find web/src -name "AgentFormBody*" -o -name "AgentBuilderChat*" -o -name "AgentWizardPage*" -o -name "agent-wizard-chat" -type d`
Expected output:
```
web/src/components/agents/AgentFormBody.tsx
web/src/components/agents/AgentBuilderChat.tsx
web/src/refresh-pages/AgentWizardPage.tsx
web/src/app/api/agent-wizard-chat
```

- [ ] **Step 4: Review git log**

Run: `cd /Users/bryantbrock/brocksoftware/meaningful-ai/onyx && git log --oneline feature/agent-wizard --not main`
Expected: Shows the spec commit + 3-4 implementation commits on the feature branch.
