"use client";

import { markdown } from "@opal/utils";
import React, { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Formik, Form, useFormikContext } from "formik";
import useSWR, { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import * as InputLayouts from "@/layouts/input-layouts";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Separator from "@/refresh-components/Separator";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import SwitchField from "@/refresh-components/form/SwitchField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import {
  SvgAddLines,
  SvgActions,
  SvgExpand,
  SvgFold,
  SvgExternalLink,
  SvgAlertCircle,
  SvgRefreshCw,
} from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Content } from "@opal/layouts";
import {
  useSettingsContext,
  useVectorDbEnabled,
} from "@/providers/SettingsProvider";
import useCCPairs from "@/hooks/useCCPairs";
import { getSourceMetadata } from "@/lib/sources";
import EmptyMessage from "@/refresh-components/EmptyMessage";
import { Settings } from "@/interfaces/settings";
import { toast } from "@/hooks/useToast";
import { useAvailableTools } from "@/hooks/useAvailableTools";
import {
  SEARCH_TOOL_ID,
  IMAGE_GENERATION_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
  PYTHON_TOOL_ID,
  OPEN_URL_TOOL_ID,
} from "@/app/app/components/tools/constants";
import { Button, Text, Card as OpalCard } from "@opal/components";
import Modal from "@/refresh-components/Modal";
import Switch from "@/refresh-components/inputs/Switch";
import useMcpServersForAgentEditor from "@/hooks/useMcpServersForAgentEditor";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import * as ExpandableCard from "@/layouts/expandable-card-layouts";
import * as ActionsLayouts from "@/layouts/actions-layouts";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { Disabled, Hoverable } from "@opal/core";
import IconButton from "@/refresh-components/buttons/IconButton";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import useFilter from "@/hooks/useFilter";
import { MCPServer } from "@/lib/tools/interfaces";
import type { IconProps } from "@opal/types";

const route = ADMIN_ROUTES.CHAT_PREFERENCES;

interface DefaultAgentConfiguration {
  tool_ids: number[];
  system_prompt: string | null;
  default_system_prompt: string;
}

interface ChatPreferencesFormValues {
  // Features
  search_ui_enabled: boolean;
  deep_research_enabled: boolean;
  auto_scroll: boolean;

  // Team context
  company_name: string;
  company_description: string;

  // Advanced
  maximum_chat_retention_days: string;
  anonymous_user_enabled: boolean;
  disable_default_assistant: boolean;

  // File limits
  user_file_max_upload_size_mb: string;
  file_token_count_threshold_k: string;
}

interface MCPServerCardTool {
  id: number;
  icon: React.FunctionComponent<IconProps>;
  name: string;
  description: string;
}

interface MCPServerCardProps {
  server: MCPServer;
  tools: MCPServerCardTool[];
  isToolEnabled: (toolDbId: number) => boolean;
  onToggleTool: (toolDbId: number, enabled: boolean) => void;
  onToggleTools: (toolDbIds: number[], enabled: boolean) => void;
}

function MCPServerCard({
  server,
  tools,
  isToolEnabled,
  onToggleTool,
  onToggleTools,
}: MCPServerCardProps) {
  const [isFolded, setIsFolded] = useState(true);
  const {
    query,
    setQuery,
    filtered: filteredTools,
  } = useFilter(tools, (tool) => `${tool.name} ${tool.description}`);

  const allToolIds = tools.map((t) => t.id);
  const serverEnabled =
    tools.length > 0 && tools.some((t) => isToolEnabled(t.id));
  const needsAuth = !server.is_authenticated;
  const authTooltip = needsAuth
    ? "Authenticate this MCP server before enabling its tools."
    : undefined;

  return (
    <ExpandableCard.Root isFolded={isFolded} onFoldedChange={setIsFolded}>
      <ActionsLayouts.Header
        title={server.name}
        description={server.description}
        icon={getActionIcon(server.server_url, server.name)}
        rightChildren={
          <SimpleTooltip tooltip={authTooltip} side="top">
            <Switch
              checked={serverEnabled}
              onCheckedChange={(checked) => onToggleTools(allToolIds, checked)}
              disabled={needsAuth}
            />
          </SimpleTooltip>
        }
      >
        {tools.length > 0 && (
          <Section flexDirection="row" gap={0.5}>
            <InputTypeIn
              placeholder="Search tools..."
              variant="internal"
              leftSearchIcon
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <Button
              rightIcon={isFolded ? SvgExpand : SvgFold}
              onClick={() => setIsFolded((prev) => !prev)}
              prominence="internal"
              size="lg"
            >
              {isFolded ? "Expand" : "Fold"}
            </Button>
          </Section>
        )}
      </ActionsLayouts.Header>
      {tools.length > 0 && filteredTools.length > 0 && (
        <ActionsLayouts.Content>
          <div className="flex flex-col gap-2">
            {filteredTools.map((tool) => (
              <ActionsLayouts.Tool
                key={tool.id}
                title={tool.name}
                description={tool.description}
                icon={tool.icon}
                rightChildren={
                  <SimpleTooltip tooltip={authTooltip} side="top">
                    <Switch
                      checked={isToolEnabled(tool.id)}
                      onCheckedChange={(checked) =>
                        onToggleTool(tool.id, checked)
                      }
                      disabled={needsAuth}
                    />
                  </SimpleTooltip>
                }
              />
            ))}
          </div>
        </ActionsLayouts.Content>
      )}
    </ExpandableCard.Root>
  );
}

type FileLimitFieldName =
  | "user_file_max_upload_size_mb"
  | "file_token_count_threshold_k";

interface NumericLimitFieldProps {
  name: FileLimitFieldName;
  defaultValue: string;
  saveSettings: (updates: Partial<Settings>) => Promise<void>;
  maxValue?: number;
  allowZero?: boolean;
}

function NumericLimitField({
  name,
  defaultValue,
  saveSettings,
  maxValue,
  allowZero = false,
}: NumericLimitFieldProps) {
  const { values, setFieldValue } =
    useFormikContext<ChatPreferencesFormValues>();
  const initialValue = useRef(values[name]);
  const restoringRef = useRef(false);
  const value = values[name];

  const parsed = parseInt(value, 10);
  const isOverMax =
    maxValue !== undefined && !isNaN(parsed) && parsed > maxValue;

  const handleRestore = () => {
    restoringRef.current = true;
    initialValue.current = defaultValue;
    void setFieldValue(name, defaultValue);
    void saveSettings({ [name]: parseInt(defaultValue, 10) });
  };

  const handleBlur = () => {
    // The restore button triggers a blur — skip since handleRestore already saved.
    if (restoringRef.current) {
      restoringRef.current = false;
      return;
    }

    const parsed = parseInt(value, 10);
    const isValid = !isNaN(parsed) && (allowZero ? parsed >= 0 : parsed > 0);

    // Revert invalid input (empty, NaN, negative).
    if (!isValid) {
      if (allowZero) {
        // Empty/invalid means "no limit" — persist 0 and clear the field.
        void setFieldValue(name, "");
        void saveSettings({ [name]: 0 });
        initialValue.current = "";
      } else {
        void setFieldValue(name, initialValue.current);
      }
      return;
    }

    // Block save when the value exceeds the hard ceiling.
    if (maxValue !== undefined && parsed > maxValue) {
      return;
    }

    // For allowZero fields, 0 means "no limit" — clear the display
    // so the "No limit" placeholder is visible, but still persist 0.
    if (allowZero && parsed === 0) {
      void setFieldValue(name, "");
      if (initialValue.current !== "") {
        void saveSettings({ [name]: 0 });
        initialValue.current = "";
      }
      return;
    }

    const normalizedDisplay = String(parsed);

    // Update the display to the canonical form (e.g. strip leading zeros).
    if (value !== normalizedDisplay) {
      void setFieldValue(name, normalizedDisplay);
    }

    // Persist only when the value actually changed.
    if (normalizedDisplay !== initialValue.current) {
      void saveSettings({ [name]: parsed });
      initialValue.current = normalizedDisplay;
    }
  };

  return (
    <Hoverable.Root group="numericLimit" widthVariant="full">
      <InputTypeInField
        name={name}
        inputMode="numeric"
        showClearButton={false}
        pattern="[0-9]*"
        placeholder={allowZero ? "No limit" : `Default: ${defaultValue}`}
        variant={isOverMax ? "error" : undefined}
        rightSection={
          (value || "") !== defaultValue ? (
            <Hoverable.Item group="numericLimit" variant="opacity-on-hover">
              <IconButton
                icon={SvgRefreshCw}
                tooltip="Restore default"
                internal
                type="button"
                onClick={handleRestore}
              />
            </Hoverable.Item>
          ) : undefined
        }
        onBlur={handleBlur}
      />
    </Hoverable.Root>
  );
}

interface FileSizeLimitFieldsProps {
  saveSettings: (updates: Partial<Settings>) => Promise<void>;
  defaultUploadSizeMb: string;
  defaultTokenThresholdK: string;
  maxAllowedUploadSizeMb?: number;
}

function FileSizeLimitFields({
  saveSettings,
  defaultUploadSizeMb,
  defaultTokenThresholdK,
  maxAllowedUploadSizeMb,
}: FileSizeLimitFieldsProps) {
  return (
    <div className="flex gap-4 w-full items-start">
      <div className="flex-1">
        <InputLayouts.Vertical
          title="File Size Limit (MB)"
          subDescription={
            maxAllowedUploadSizeMb
              ? `Max: ${maxAllowedUploadSizeMb} MB`
              : undefined
          }
          nonInteractive
        >
          <NumericLimitField
            name="user_file_max_upload_size_mb"
            defaultValue={defaultUploadSizeMb}
            saveSettings={saveSettings}
            maxValue={maxAllowedUploadSizeMb}
          />
        </InputLayouts.Vertical>
      </div>
      <div className="flex-1">
        <InputLayouts.Vertical
          title="File Token Limit (thousand tokens)"
          nonInteractive
        >
          <NumericLimitField
            name="file_token_count_threshold_k"
            defaultValue={defaultTokenThresholdK}
            saveSettings={saveSettings}
            allowZero
          />
        </InputLayouts.Vertical>
      </div>
    </div>
  );
}

/**
 * Inner form component that uses useFormikContext to access values
 * and create save handlers for settings fields.
 */
function ChatPreferencesForm() {
  const router = useRouter();
  const settings = useSettingsContext();
  const { values } = useFormikContext<ChatPreferencesFormValues>();

  // Track initial text values to avoid unnecessary saves on blur
  const initialCompanyName = useRef(values.company_name);
  const initialCompanyDescription = useRef(values.company_description);

  // Tools availability
  const { tools: availableTools } = useAvailableTools();
  const vectorDbEnabled = useVectorDbEnabled();

  const searchTool = availableTools.find(
    (t) => t.in_code_tool_id === SEARCH_TOOL_ID
  );
  const imageGenTool = availableTools.find(
    (t) => t.in_code_tool_id === IMAGE_GENERATION_TOOL_ID
  );
  const webSearchTool = availableTools.find(
    (t) => t.in_code_tool_id === WEB_SEARCH_TOOL_ID
  );
  const openURLTool = availableTools.find(
    (t) => t.in_code_tool_id === OPEN_URL_TOOL_ID
  );
  const codeInterpreterTool = availableTools.find(
    (t) => t.in_code_tool_id === PYTHON_TOOL_ID
  );

  // Connectors
  const { ccPairs } = useCCPairs();
  const uniqueSources = Array.from(new Set(ccPairs.map((p) => p.source)));

  // MCP servers and OpenAPI tools
  const { mcpData } = useMcpServersForAgentEditor();
  const { openApiTools: openApiToolsRaw } = useOpenApiTools();
  const mcpServers = mcpData?.mcp_servers ?? [];
  const openApiTools = openApiToolsRaw ?? [];

  const mcpServersWithTools = mcpServers.map((server) => ({
    server,
    tools: availableTools
      .filter((tool) => tool.mcp_server_id === server.id)
      .map((tool) => ({
        id: tool.id,
        icon: getActionIcon(server.server_url, server.name),
        name: tool.display_name || tool.name,
        description: tool.description,
      })),
  }));

  // Default agent configuration (system prompt)
  const { data: defaultAgentConfig, mutate: mutateDefaultAgent } =
    useSWR<DefaultAgentConfiguration>(
      "/api/admin/default-assistant/configuration",
      errorHandlingFetcher
    );

  const enabledToolIds = defaultAgentConfig?.tool_ids ?? [];

  const isToolEnabled = useCallback(
    (toolDbId: number) => enabledToolIds.includes(toolDbId),
    [enabledToolIds]
  );

  const saveToolIds = useCallback(
    async (newToolIds: number[]) => {
      // Optimistic update so subsequent toggles read fresh state
      const optimisticData = defaultAgentConfig
        ? { ...defaultAgentConfig, tool_ids: newToolIds }
        : undefined;
      try {
        await mutateDefaultAgent(
          async () => {
            const response = await fetch("/api/admin/default-assistant", {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ tool_ids: newToolIds }),
            });
            if (!response.ok) {
              const errorMsg = (await response.json()).detail;
              throw new Error(errorMsg);
            }
            return optimisticData;
          },
          { optimisticData, revalidate: true }
        );
        toast.success("Tools updated");
      } catch {
        toast.error("Failed to update tools");
      }
    },
    [defaultAgentConfig, mutateDefaultAgent]
  );

  const toggleTool = useCallback(
    (toolDbId: number, enabled: boolean) => {
      const newToolIds = enabled
        ? [...enabledToolIds, toolDbId]
        : enabledToolIds.filter((id) => id !== toolDbId);
      void saveToolIds(newToolIds);
    },
    [enabledToolIds, saveToolIds]
  );

  const toggleTools = useCallback(
    (toolDbIds: number[], enabled: boolean) => {
      const idsSet = new Set(toolDbIds);
      const withoutIds = enabledToolIds.filter((id) => !idsSet.has(id));
      const newToolIds = enabled ? [...withoutIds, ...toolDbIds] : withoutIds;
      void saveToolIds(newToolIds);
    },
    [enabledToolIds, saveToolIds]
  );

  // System prompt modal state
  const [systemPromptModalOpen, setSystemPromptModalOpen] = useState(false);

  const saveSettings = useCallback(
    async (updates: Partial<Settings>) => {
      const currentSettings = settings?.settings;
      if (!currentSettings) return;

      const newSettings = { ...currentSettings, ...updates };

      try {
        const response = await fetch("/api/admin/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(newSettings),
        });

        if (!response.ok) {
          const errorMsg = (await response.json()).detail;
          throw new Error(errorMsg);
        }

        router.refresh();
        await mutate(SWR_KEYS.settings);
        toast.success("Settings updated");
      } catch (error) {
        toast.error("Failed to update settings");
      }
    },
    [settings, router]
  );

  return (
    <>
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description="Organization-wide chat settings and defaults. Users can override some of these in their personal settings."
          separator
        />

        <SettingsLayouts.Body>
          {/* Team Context */}
          <Section gap={1}>
            <InputLayouts.Vertical
              title="Team Name"
              subDescription="This is added to all chat sessions as additional context to provide a richer/customized experience."
            >
              <InputTypeInField
                name="company_name"
                placeholder="Enter team name"
                onBlur={() => {
                  if (values.company_name !== initialCompanyName.current) {
                    void saveSettings({
                      company_name: values.company_name || null,
                    });
                    initialCompanyName.current = values.company_name;
                  }
                }}
              />
            </InputLayouts.Vertical>

            <InputLayouts.Vertical
              title="Team Context"
              subDescription="Users can also provide additional individual context in their personal settings."
            >
              <InputTextAreaField
                name="company_description"
                placeholder="Describe your team and how Onyx should behave."
                rows={4}
                maxRows={10}
                autoResize
                onBlur={() => {
                  if (
                    values.company_description !==
                    initialCompanyDescription.current
                  ) {
                    void saveSettings({
                      company_description: values.company_description || null,
                    });
                    initialCompanyDescription.current =
                      values.company_description;
                  }
                }}
              />
            </InputLayouts.Vertical>
          </Section>

          <InputLayouts.Horizontal
            title="System Prompt"
            description="Base prompt for all chats, agents, and projects. Modify with caution: Significant changes may degrade response quality."
          >
            <Button
              prominence="tertiary"
              icon={SvgAddLines}
              onClick={() => setSystemPromptModalOpen(true)}
            >
              Modify Prompt
            </Button>
          </InputLayouts.Horizontal>

          <Separator noPadding />

          {/* Features */}
          <Section gap={0.75}>
            <Content
              title="Features"
              sizePreset="main-content"
              variant="section"
            />
            <Card>
              <SimpleTooltip
                tooltip={
                  uniqueSources.length === 0
                    ? "Set up connectors to use Search Mode"
                    : undefined
                }
                side="top"
              >
                <Disabled disabled={uniqueSources.length === 0} allowClick>
                  <div className="w-full">
                    <InputLayouts.Horizontal
                      title="Search Mode"
                      description="UI mode for quick document search across your organization."
                      disabled={uniqueSources.length === 0}
                    >
                      <SwitchField
                        name="search_ui_enabled"
                        onCheckedChange={(checked) => {
                          void saveSettings({ search_ui_enabled: checked });
                        }}
                        disabled={uniqueSources.length === 0}
                      />
                    </InputLayouts.Horizontal>
                  </div>
                </Disabled>
              </SimpleTooltip>
              <InputLayouts.Horizontal
                title="Deep Research"
                description="Agentic research system that works across the web and connected sources. Uses significantly more tokens per query."
              >
                <SwitchField
                  name="deep_research_enabled"
                  onCheckedChange={(checked) => {
                    void saveSettings({ deep_research_enabled: checked });
                  }}
                />
              </InputLayouts.Horizontal>
              <InputLayouts.Horizontal
                title="Chat Auto-Scroll"
                description="Automatically scroll to new content as chat generates response. Users can override this in their personal settings."
              >
                <SwitchField
                  name="auto_scroll"
                  onCheckedChange={(checked) => {
                    void saveSettings({ auto_scroll: checked });
                  }}
                />
              </InputLayouts.Horizontal>
            </Card>
          </Section>

          <Separator noPadding />

          <Disabled disabled={values.disable_default_assistant}>
            <div>
              <Section gap={1.5}>
                {/* Connectors */}
                <Section gap={0.75}>
                  <Content
                    title="Connectors"
                    sizePreset="main-content"
                    variant="section"
                  />

                  <Section
                    flexDirection="row"
                    justifyContent="between"
                    alignItems="center"
                    gap={0.25}
                  >
                    {uniqueSources.length === 0 ? (
                      <EmptyMessage title="No connectors set up" />
                    ) : (
                      <>
                        <Section
                          flexDirection="row"
                          justifyContent="start"
                          alignItems="center"
                          gap={0.25}
                        >
                          {uniqueSources.slice(0, 3).map((source) => {
                            const meta = getSourceMetadata(source);
                            return (
                              <Card
                                key={source}
                                padding={0.75}
                                className="w-[10rem]"
                              >
                                <Content
                                  icon={meta.icon}
                                  title={meta.displayName}
                                  sizePreset="main-ui"
                                />
                              </Card>
                            );
                          })}
                        </Section>

                        <Button
                          href="/admin/indexing/status"
                          prominence="tertiary"
                          rightIcon={SvgExternalLink}
                        >
                          Manage All
                        </Button>
                      </>
                    )}
                  </Section>
                </Section>

                {/* Actions & Tools */}
                <SimpleCollapsible>
                  <SimpleCollapsible.Header
                    title="Actions & Tools"
                    description="Tools and capabilities available for chat to use. This does not apply to agents."
                  />
                  <SimpleCollapsible.Content>
                    <Section gap={0.5}>
                      {vectorDbEnabled && searchTool && (
                        <Card>
                          <InputLayouts.Horizontal
                            title="Internal Search"
                            description="Search through your organization's connected knowledge base and documents."
                          >
                            <Switch
                              checked={isToolEnabled(searchTool.id)}
                              onCheckedChange={(checked) =>
                                void toggleTool(searchTool.id, checked)
                              }
                            />
                          </InputLayouts.Horizontal>
                        </Card>
                      )}

                      <SimpleTooltip
                        tooltip={
                          imageGenTool
                            ? undefined
                            : "Image generation requires a configured model. Set one up under Configuration > Image Generation, or ask an admin."
                        }
                        side="top"
                      >
                        <Card variant={imageGenTool ? undefined : "disabled"}>
                          <InputLayouts.Horizontal
                            title="Image Generation"
                            description="Generate and manipulate images using AI-powered tools."
                            disabled={!imageGenTool}
                          >
                            <Switch
                              checked={
                                imageGenTool
                                  ? isToolEnabled(imageGenTool.id)
                                  : false
                              }
                              onCheckedChange={(checked) =>
                                imageGenTool &&
                                void toggleTool(imageGenTool.id, checked)
                              }
                              disabled={!imageGenTool}
                            />
                          </InputLayouts.Horizontal>
                        </Card>
                      </SimpleTooltip>

                      <Card variant={webSearchTool ? undefined : "disabled"}>
                        <InputLayouts.Horizontal
                          title="Web Search"
                          description="Search the web for real-time information and up-to-date results."
                          disabled={!webSearchTool}
                        >
                          <Switch
                            checked={
                              webSearchTool
                                ? isToolEnabled(webSearchTool.id)
                                : false
                            }
                            onCheckedChange={(checked) =>
                              webSearchTool &&
                              void toggleTool(webSearchTool.id, checked)
                            }
                            disabled={!webSearchTool}
                          />
                        </InputLayouts.Horizontal>
                      </Card>

                      <Card variant={openURLTool ? undefined : "disabled"}>
                        <InputLayouts.Horizontal
                          title="Open URL"
                          description="Fetch and read content from web URLs."
                          disabled={!openURLTool}
                        >
                          <Switch
                            checked={
                              openURLTool
                                ? isToolEnabled(openURLTool.id)
                                : false
                            }
                            onCheckedChange={(checked) =>
                              openURLTool &&
                              void toggleTool(openURLTool.id, checked)
                            }
                            disabled={!openURLTool}
                          />
                        </InputLayouts.Horizontal>
                      </Card>

                      <Card
                        variant={codeInterpreterTool ? undefined : "disabled"}
                      >
                        <InputLayouts.Horizontal
                          title="Code Interpreter"
                          description="Generate and run code."
                          disabled={!codeInterpreterTool}
                        >
                          <Switch
                            checked={
                              codeInterpreterTool
                                ? isToolEnabled(codeInterpreterTool.id)
                                : false
                            }
                            onCheckedChange={(checked) =>
                              codeInterpreterTool &&
                              void toggleTool(codeInterpreterTool.id, checked)
                            }
                            disabled={!codeInterpreterTool}
                          />
                        </InputLayouts.Horizontal>
                      </Card>
                    </Section>

                    {/* Separator between built-in tools and MCP/OpenAPI tools */}
                    {(mcpServersWithTools.length > 0 ||
                      openApiTools.length > 0) && (
                      <Separator noPadding className="py-3" />
                    )}

                    {/* MCP Servers & OpenAPI Tools */}
                    <Section gap={0.5}>
                      {mcpServersWithTools.map(({ server, tools }) => (
                        <MCPServerCard
                          key={server.id}
                          server={server}
                          tools={tools}
                          isToolEnabled={isToolEnabled}
                          onToggleTool={toggleTool}
                          onToggleTools={toggleTools}
                        />
                      ))}
                      {openApiTools.map((tool) => (
                        <ExpandableCard.Root key={tool.id} defaultFolded>
                          <ActionsLayouts.Header
                            title={tool.display_name || tool.name}
                            description={tool.description}
                            icon={SvgActions}
                            rightChildren={
                              <Switch
                                checked={isToolEnabled(tool.id)}
                                onCheckedChange={(checked) =>
                                  toggleTool(tool.id, checked)
                                }
                              />
                            }
                          />
                        </ExpandableCard.Root>
                      ))}
                    </Section>
                  </SimpleCollapsible.Content>
                </SimpleCollapsible>
              </Section>
            </div>
          </Disabled>

          <Separator noPadding />

          {/* Advanced Options */}
          <SimpleCollapsible defaultOpen={false}>
            <SimpleCollapsible.Header title="Advanced Options" />
            <SimpleCollapsible.Content>
              <Section gap={1}>
                <Card>
                  <InputLayouts.Horizontal
                    title="Keep Chat History"
                    description="Specify how long Onyx should retain chats in your organization."
                  >
                    <InputSelectField
                      name="maximum_chat_retention_days"
                      onValueChange={(value) => {
                        void saveSettings({
                          maximum_chat_retention_days:
                            value === "forever" ? null : parseInt(value, 10),
                        });
                      }}
                    >
                      <InputSelect.Trigger />
                      <InputSelect.Content>
                        <InputSelect.Item value="forever">
                          Forever
                        </InputSelect.Item>
                        <InputSelect.Item value="7">7 days</InputSelect.Item>
                        <InputSelect.Item value="30">30 days</InputSelect.Item>
                        <InputSelect.Item value="90">90 days</InputSelect.Item>
                        <InputSelect.Item value="365">
                          365 days
                        </InputSelect.Item>
                      </InputSelect.Content>
                    </InputSelectField>
                  </InputLayouts.Horizontal>
                </Card>

                <Card>
                  <InputLayouts.Vertical
                    title="File Attachment Size Limit"
                    description="Files attached in chats and projects must fit within both limits to be accepted. Larger files increase latency, memory usage, and token costs."
                  >
                    <FileSizeLimitFields
                      saveSettings={saveSettings}
                      defaultUploadSizeMb={
                        settings?.settings.default_user_file_max_upload_size_mb?.toString() ??
                        "100"
                      }
                      defaultTokenThresholdK={
                        settings?.settings.default_file_token_count_threshold_k?.toString() ??
                        "200"
                      }
                      maxAllowedUploadSizeMb={
                        settings?.settings.max_allowed_upload_size_mb
                      }
                    />
                  </InputLayouts.Vertical>
                </Card>

                <Card>
                  <InputLayouts.Horizontal
                    title="Allow Anonymous Users"
                    description="Allow anyone to start chats without logging in. They do not see any other chats and cannot create agents or update settings."
                  >
                    <SwitchField
                      name="anonymous_user_enabled"
                      onCheckedChange={(checked) => {
                        void saveSettings({ anonymous_user_enabled: checked });
                      }}
                    />
                  </InputLayouts.Horizontal>

                  <InputLayouts.Horizontal
                    title="Always Start with an Agent"
                    description="This removes the default chat. Users will always start in an agent, and new chats will be created in their last active agent. Set featured agents to help new users get started."
                  >
                    <SwitchField
                      name="disable_default_assistant"
                      onCheckedChange={(checked) => {
                        void saveSettings({
                          disable_default_assistant: checked,
                        });
                      }}
                    />
                  </InputLayouts.Horizontal>
                </Card>
              </Section>
            </SimpleCollapsible.Content>
          </SimpleCollapsible>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      <Modal
        open={systemPromptModalOpen}
        onOpenChange={setSystemPromptModalOpen}
      >
        <Modal.Content width="xl" height="fit">
          <Formik
            initialValues={{
              system_prompt:
                defaultAgentConfig?.system_prompt ??
                defaultAgentConfig?.default_system_prompt ??
                "",
            }}
            onSubmit={async ({ system_prompt }) => {
              try {
                const response = await fetch("/api/admin/default-assistant", {
                  method: "PATCH",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ system_prompt }),
                });
                if (!response.ok) {
                  const errorMsg = (await response.json()).detail;
                  throw new Error(errorMsg);
                }
                await mutateDefaultAgent();
                setSystemPromptModalOpen(false);
                toast.success("System prompt updated");
              } catch {
                toast.error("Failed to update system prompt");
              }
            }}
          >
            {({ dirty, isSubmitting, submitForm }) => (
              <Form>
                <Modal.Header
                  icon={SvgAddLines}
                  title="System Prompt"
                  description="This base prompt is prepended to all chats, agents, and projects."
                  onClose={() => setSystemPromptModalOpen(false)}
                />
                <Modal.Body>
                  <Section gap={0.25} alignItems="start">
                    <InputTextAreaField
                      name="system_prompt"
                      placeholder="Enter your system prompt..."
                      rows={8}
                      maxRows={20}
                      autoResize
                    />
                    <Text font="secondary-body" color="text-03">
                      {markdown(
                        "You can use the following placeholders in your prompt:\n`{{CURRENT_DATETIME}}` - Current date and day of the week in a human-readable format.\n`{{CITATION_GUIDANCE}}` - Instructions for providing citations when facts are retrieved from search tools.\nOnly included when search tools are used."
                      )}
                    </Text>
                  </Section>
                  <OpalCard background="none" border="solid" padding="sm">
                    <Content
                      sizePreset="main-ui"
                      icon={SvgAlertCircle}
                      title="Modify with caution."
                      description="System prompt affects all chats, agents, and projects. Significant changes may degrade response quality."
                    />
                  </OpalCard>
                </Modal.Body>
                <Modal.Footer>
                  <Button
                    prominence="secondary"
                    onClick={() => setSystemPromptModalOpen(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    prominence="primary"
                    onClick={submitForm}
                    disabled={!dirty || isSubmitting}
                  >
                    Save
                  </Button>
                </Modal.Footer>
              </Form>
            )}
          </Formik>
        </Modal.Content>
      </Modal>
    </>
  );
}

export default function ChatPreferencesPage() {
  const settings = useSettingsContext();

  const initialValues: ChatPreferencesFormValues = {
    // Features
    search_ui_enabled: settings.settings.search_ui_enabled ?? false,
    deep_research_enabled: settings.settings.deep_research_enabled ?? true,
    auto_scroll: settings.settings.auto_scroll ?? false,

    // Team context
    company_name: settings.settings.company_name ?? "",
    company_description: settings.settings.company_description ?? "",

    // Advanced
    maximum_chat_retention_days:
      settings.settings.maximum_chat_retention_days?.toString() ?? "forever",
    anonymous_user_enabled: settings.settings.anonymous_user_enabled ?? false,
    disable_default_assistant:
      settings.settings.disable_default_assistant ?? false,

    // File limits — for upload size: 0/null means "use default";
    // for token threshold: null means "use default", 0 means "no limit".
    user_file_max_upload_size_mb:
      (settings.settings.user_file_max_upload_size_mb ?? 0) <= 0
        ? settings.settings.default_user_file_max_upload_size_mb?.toString() ??
          "100"
        : settings.settings.user_file_max_upload_size_mb!.toString(),
    file_token_count_threshold_k:
      settings.settings.file_token_count_threshold_k == null
        ? settings.settings.default_file_token_count_threshold_k?.toString() ??
          "200"
        : settings.settings.file_token_count_threshold_k === 0
          ? ""
          : settings.settings.file_token_count_threshold_k.toString(),
  };

  return (
    <Formik
      initialValues={initialValues}
      onSubmit={() => {}}
      enableReinitialize
    >
      <Form className="h-full w-full">
        <ChatPreferencesForm />
      </Form>
    </Formik>
  );
}
