"use client";

import { useCallback, useRef } from "react";
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
import { SvgBubbleText } from "@opal/icons";
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
  temperature_override_enabled: boolean;
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
        <Section gap={0.75}>
          <InputLayouts.Vertical
            title="Team Name"
            description="This is added to all chat sessions as additional context to provide a richer/customized experience."
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
            description="Users can also provide additional individual context in their personal settings."
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

        <Separator noPadding />

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
                  <SwitchField name="web_search" disabled={!webSearchTool} />
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

              <Card variant={codeInterpreterTool ? undefined : "disabled"}>
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
                  <SwitchField name="file_reader" disabled={!fileReaderTool} />
                </InputLayouts.Horizontal>
              </Card>
            </Section>
          </SimpleCollapsible.Content>
        </SimpleCollapsible>

        <Separator noPadding />

        {/* Advanced Options */}
        <SimpleCollapsible>
          <SimpleCollapsible.Header title="Advanced Options" />
          <SimpleCollapsible.Content>
            <Card>
              <InputLayouts.Horizontal
                title="Temperature Override"
                description="Allow users to override the default temperature for each assistant."
              >
                <SwitchField
                  name="temperature_override_enabled"
                  onCheckedChange={(checked) => {
                    void saveSettings({
                      temperature_override_enabled: checked,
                    });
                  }}
                />
              </InputLayouts.Horizontal>

              <InputLayouts.Horizontal
                title="Disable Default Assistant"
                description="When enabled, the 'New Session' button will start a new chat with the current agent instead of the default assistant."
              >
                <SwitchField
                  name="disable_default_assistant"
                  onCheckedChange={(checked) => {
                    void saveSettings({ disable_default_assistant: checked });
                  }}
                />
              </InputLayouts.Horizontal>
            </Card>
          </SimpleCollapsible.Content>
        </SimpleCollapsible>
      </SettingsLayouts.Body>
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
    temperature_override_enabled:
      settings.settings.temperature_override_enabled ?? false,
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
