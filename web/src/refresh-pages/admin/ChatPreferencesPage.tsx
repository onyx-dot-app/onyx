"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Formik, Form, useFormikContext } from "formik";
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
import { SvgBubbleText, SvgAddLines, SvgActions } from "@opal/icons";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { Settings } from "@/interfaces/settings";
import { toast } from "@/hooks/useToast";
import { useAvailableTools } from "@/hooks/useAvailableTools";
import {
  IMAGE_GENERATION_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
  PYTHON_TOOL_ID,
  OPEN_URL_TOOL_ID,
  FILE_READER_TOOL_ID,
} from "@/app/app/components/tools/constants";
import { Button } from "@opal/components";
import Modal from "@/refresh-components/Modal";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import Switch from "@/refresh-components/inputs/Switch";
import useMcpServersForAgentEditor from "@/hooks/useMcpServersForAgentEditor";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import * as ExpandableCard from "@/layouts/expandable-card-layouts";
import * as ActionsLayouts from "@/layouts/actions-layouts";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import Disabled from "@/refresh-components/Disabled";

interface ChatPreferencesFormValues {
  // Features
  search_ui_enabled: boolean;
  deep_research_enabled: boolean;
  auto_scroll: boolean;

  // Team context
  company_name: string;
  company_description: string;

  // Tools (built-in)
  image_generation: boolean;
  web_search: boolean;
  open_url: boolean;
  code_interpreter: boolean;
  file_reader: boolean;

  // Advanced
  maximum_chat_retention_days: string;
  anonymous_user_enabled: boolean;
  disable_default_assistant: boolean;
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
  const fileReaderTool = availableTools.find(
    (t) => t.in_code_tool_id === FILE_READER_TOOL_ID
  );

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
        id: tool.id.toString(),
        icon: getActionIcon(server.server_url, server.name),
        name: tool.display_name || tool.name,
        description: tool.description,
      })),
  }));

  // System prompt modal state
  const [systemPromptModalOpen, setSystemPromptModalOpen] = useState(false);
  const [systemPromptValue, setSystemPromptValue] = useState("");

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
        toast.success("Settings updated");
      } catch (error) {
        toast.error("Failed to update settings");
      }
    },
    [settings, router]
  );

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgBubbleText}
        title="Chat Preferences"
        description="Organization-wide chat settings and defaults. Users can override some of these in their personal settings."
        separator
      />

      <SettingsLayouts.Body>
        {/* Features */}
        <Section gap={0.75}>
          <InputLayouts.Title title="Features" />
          <Card>
            <InputLayouts.Horizontal
              title="Search Mode"
              description="UI mode for quick document search across your organization."
            >
              <SwitchField
                name="search_ui_enabled"
                onCheckedChange={(checked) => {
                  void saveSettings({ search_ui_enabled: checked });
                }}
              />
            </InputLayouts.Horizontal>

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

        <Disabled disabled={values.disable_default_assistant}>
          <div>
            <Section gap={1.5}>
              {/* Connectors */}
              <Section gap={0.75}>
                <InputLayouts.Title title="Connectors" />
                {/* TODO: Add connector selection UI */}
              </Section>

              {/* Actions & Tools */}
              <SimpleCollapsible>
                <SimpleCollapsible.Header
                  title="Actions & Tools"
                  description="Tools and capabilities available for chat to use. This does not apply to agents."
                />
                <SimpleCollapsible.Content>
                  <Section gap={0.5}>
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
                          <SwitchField
                            name="image_generation"
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
                        <SwitchField
                          name="web_search"
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
                        <SwitchField name="open_url" disabled={!openURLTool} />
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
                        <SwitchField
                          name="code_interpreter"
                          disabled={!codeInterpreterTool}
                        />
                      </InputLayouts.Horizontal>
                    </Card>

                    <Card variant={fileReaderTool ? undefined : "disabled"}>
                      <InputLayouts.Horizontal
                        title="File Reader"
                        description="Read sections of uploaded files. Required for files that exceed the context window."
                        disabled={!fileReaderTool}
                      >
                        <SwitchField
                          name="file_reader"
                          disabled={!fileReaderTool}
                        />
                      </InputLayouts.Horizontal>
                    </Card>
                  </Section>

                  {/* MCP Servers */}
                  {mcpServersWithTools.length > 0 && (
                    <Section gap={0.5}>
                      {mcpServersWithTools.map(({ server, tools }) => (
                        <ExpandableCard.Root key={server.id} defaultFolded>
                          <ActionsLayouts.Header
                            title={server.name}
                            description={server.description}
                            icon={getActionIcon(server.server_url, server.name)}
                            rightChildren={<Switch defaultChecked={false} />}
                          />
                          {tools.length > 0 && (
                            <ActionsLayouts.Content>
                              {tools.map((tool) => (
                                <ActionsLayouts.Tool
                                  key={tool.id}
                                  title={tool.name}
                                  description={tool.description}
                                  icon={tool.icon}
                                  rightChildren={
                                    <Switch defaultChecked={false} />
                                  }
                                />
                              ))}
                            </ActionsLayouts.Content>
                          )}
                        </ExpandableCard.Root>
                      ))}
                    </Section>
                  )}

                  {/* OpenAPI Tools */}
                  {openApiTools.length > 0 && (
                    <Section gap={0.5}>
                      {openApiTools.map((tool) => (
                        <ExpandableCard.Root key={tool.id} defaultFolded>
                          <ActionsLayouts.Header
                            title={tool.display_name || tool.name}
                            description={tool.description}
                            icon={SvgActions}
                            rightChildren={<Switch defaultChecked={false} />}
                          />
                        </ExpandableCard.Root>
                      ))}
                    </Section>
                  )}
                </SimpleCollapsible.Content>
              </SimpleCollapsible>
            </Section>
          </div>
        </Disabled>

        <Separator noPadding />

        {/* Advanced Options */}
        <SimpleCollapsible>
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
                      <InputSelect.Item value="365">365 days</InputSelect.Item>
                    </InputSelect.Content>
                  </InputSelectField>
                </InputLayouts.Horizontal>
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
                      void saveSettings({ disable_default_assistant: checked });
                    }}
                  />
                </InputLayouts.Horizontal>
              </Card>
            </Section>
          </SimpleCollapsible.Content>
        </SimpleCollapsible>
      </SettingsLayouts.Body>

      <Modal
        open={systemPromptModalOpen}
        onOpenChange={setSystemPromptModalOpen}
      >
        <Modal.Content width="md" height="fit">
          <Modal.Header
            icon={SvgAddLines}
            title="System Prompt"
            description="This base prompt is prepended to all chats, agents, and projects."
            onClose={() => setSystemPromptModalOpen(false)}
          />
          <Modal.Body>
            <InputTextArea
              value={systemPromptValue}
              onChange={(e) => setSystemPromptValue(e.target.value)}
              placeholder="Enter your system prompt..."
              rows={8}
              maxRows={20}
              autoResize
            />
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
              onClick={() => {
                // TODO: Wire to backend when system_prompt is added to Settings
                setSystemPromptModalOpen(false);
                toast.success("System prompt updated");
              }}
            >
              Save
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </SettingsLayouts.Root>
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

    // Tools — default to false; actual state depends on per-agent config
    image_generation: false,
    web_search: false,
    open_url: false,
    code_interpreter: false,
    file_reader: false,

    // Advanced
    maximum_chat_retention_days:
      settings.settings.maximum_chat_retention_days?.toString() ?? "forever",
    anonymous_user_enabled: settings.settings.anonymous_user_enabled ?? false,
    disable_default_assistant:
      settings.settings.disable_default_assistant ?? false,
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
