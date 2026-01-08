"use client";

import { useState } from "react";
import { Formik, Form } from "formik";
import { ThreeDotsLoader } from "@/components/Loading";
import { useRouter } from "next/navigation";
import { AdminPageTitle } from "@/components/admin/Title";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Text from "@/refresh-components/texts/Text";
import useSWR, { mutate } from "swr";
import { ErrorCallout } from "@/components/ErrorCallout";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useAgents } from "@/hooks/useAgents";
import Separator from "@/refresh-components/Separator";
import { SubLabel } from "@/components/Field";
import Button from "@/refresh-components/buttons/Button";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import Link from "next/link";
import { Callout } from "@/components/ui/callout";
import { ToolSnapshot, MCPServersResponse } from "@/lib/tools/interfaces";
import { ToolSelector } from "@/components/admin/assistants/ToolSelector";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import { HoverPopup } from "@/components/HoverPopup";
import { Info } from "lucide-react";
import { SvgOnyxLogo } from "@opal/icons";

interface DefaultAssistantConfiguration {
  tool_ids: number[];
  system_prompt: string | null;
  default_system_prompt: string;
}

interface DefaultAssistantUpdateRequest {
  tool_ids?: number[];
  system_prompt?: string | null;
}

function DefaultAssistantConfig() {
  const router = useRouter();
  const { popup, setPopup } = usePopup();
  const { refresh: refreshAgents } = useAgents();
  const combinedSettings = useSettingsContext();

  const {
    data: config,
    isLoading,
    error,
  } = useSWR<DefaultAssistantConfiguration>(
    "/api/admin/default-assistant/configuration",
    errorHandlingFetcher
  );

  // Use the same endpoint as regular assistant editor
  const { data: tools } = useSWR<ToolSnapshot[]>(
    "/api/tool",
    errorHandlingFetcher
  );

  const { data: mcpServersResponse } = useSWR<MCPServersResponse>(
    "/api/admin/mcp/servers",
    errorHandlingFetcher
  );

  const [isSubmitting, setIsSubmitting] = useState(false);

  const persistConfiguration = async (
    updates: DefaultAssistantUpdateRequest
  ) => {
    const response = await fetch("/api/admin/default-assistant", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || "Failed to update assistant");
    }
  };

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  if (error) {
    return (
      <ErrorCallout
        errorTitle="Failed to load configuration"
        errorMsg="Unable to fetch the default assistant configuration."
      />
    );
  }

  if (combinedSettings?.settings?.disable_default_assistant) {
    return (
      <div>
        {popup}
        <Callout type="notice">
          <p className="mb-3">
            The default assistant is currently disabled in your workspace
            settings.
          </p>
          <p>
            To configure the default assistant, you must first enable it in{" "}
            <Link href="/admin/settings" className="text-link font-medium">
              Workspace Settings
            </Link>
            .
          </p>
        </Callout>
      </div>
    );
  }

  if (!config || !tools) {
    return <ThreeDotsLoader />;
  }

  const enabledToolsMap: { [key: number]: boolean } = {};
  tools.forEach((tool) => {
    // Enable tool if it's in the current config OR if it's marked as default_enabled
    enabledToolsMap[tool.id] =
      config.tool_ids.includes(tool.id) || tool.default_enabled;
  });

  return (
    <div>
      {popup}
      <Formik
        enableReinitialize
        initialValues={{
          enabled_tools_map: enabledToolsMap,
          // Display the default prompt when system_prompt is null
          system_prompt: config.system_prompt ?? config.default_system_prompt,
          // Track if we're using the default (null in DB)
          isUsingDefault: config.system_prompt === null,
        }}
        onSubmit={async (values) => {
          setIsSubmitting(true);
          try {
            const enabledToolIds = Object.keys(values.enabled_tools_map)
              .map((id) => Number(id))
              .filter((id) => values.enabled_tools_map[id]);

            const updates: DefaultAssistantUpdateRequest = {
              tool_ids: enabledToolIds,
            };

            // Determine if we need to send system_prompt
            // Use config directly since it reflects the original DB state
            const wasUsingDefault = config.system_prompt === null;
            const initialPrompt =
              config.system_prompt ?? config.default_system_prompt;
            const isNowUsingDefault = values.isUsingDefault;
            const promptChanged = values.system_prompt !== initialPrompt;

            if (wasUsingDefault && isNowUsingDefault && !promptChanged) {
              // Was default, still default, no changes - don't send
            } else if (isNowUsingDefault) {
              // User clicked reset - send null to set DB to null (use default)
              updates.system_prompt = null;
            } else if (promptChanged || wasUsingDefault !== isNowUsingDefault) {
              // Prompt changed or switched from default to custom
              updates.system_prompt = values.system_prompt;
            }

            await persistConfiguration(updates);

            await mutate("/api/admin/default-assistant/configuration");
            router.refresh();
            await refreshAgents();

            setPopup({
              message: "Default assistant updated successfully!",
              type: "success",
            });
          } catch (error: any) {
            setPopup({
              message: error.message || "Failed to update assistant",
              type: "error",
            });
          } finally {
            setIsSubmitting(false);
          }
        }}
      >
        {({ values, setFieldValue }) => (
          <Form>
            <div className="space-y-6">
              <div className="mt-4">
                <Text as="p" className="text-text-dark">
                  Configure which capabilities are enabled for the default
                  assistant in chat. These settings apply to all users who
                  haven&apos;t customized their assistant preferences.
                </Text>
              </div>

              <Separator />

              <div className="max-w-4xl">
                <div className="flex gap-x-2 items-center">
                  <Text
                    as="p"
                    mainUiBody
                    text04
                    className="font-medium text-sm"
                  >
                    Instructions
                  </Text>
                </div>
                <div className="flex items-start gap-1.5 mb-1">
                  <SubLabel>
                    Add instructions to tailor the behavior of the assistant.
                  </SubLabel>
                  <HoverPopup
                    mainContent={
                      <Info className="h-3.5 w-3.5 text-text-400 cursor-help" />
                    }
                    popupContent={
                      <div className="text-xs space-y-1.5 max-w-xs bg-background-neutral-dark-03 text-text-light-05">
                        <div>You can use placeholders in your prompt:</div>
                        <div>
                          <span className="font-mono font-semibold">
                            {"{{CURRENT_DATETIME}}"}
                          </span>{" "}
                          - Injects the current date and day of the week in a
                          human/LLM readable format.
                        </div>
                        <div>
                          <span className="font-mono font-semibold">
                            {"{{CITATION_GUIDANCE}}"}
                          </span>{" "}
                          - Injects instructions to provide citations for facts
                          found from search tools. This is not included if no
                          search tools are called.
                        </div>
                      </div>
                    }
                    direction="bottom"
                  />
                </div>
                <div>
                  <InputTextArea
                    rows={8}
                    value={values.system_prompt}
                    onChange={(event) => {
                      setFieldValue("system_prompt", event.target.value);
                      // Mark as no longer using default when user edits
                      if (values.isUsingDefault) {
                        setFieldValue("isUsingDefault", false);
                      }
                    }}
                    placeholder="You are a professional email writing assistant that always uses a polite enthusiastic tone, emphasizes action items, and leaves blanks for the human to fill in when you have unknowns"
                  />
                  <div className="flex justify-between items-center mt-2">
                    <button
                      type="button"
                      className="text-sm text-link hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
                      disabled={values.isUsingDefault}
                      onClick={() => {
                        setFieldValue(
                          "system_prompt",
                          config.default_system_prompt
                        );
                        setFieldValue("isUsingDefault", true);
                      }}
                    >
                      Reset to Default
                    </button>
                    <Text as="p" mainUiMuted text03 className="text-sm">
                      {values.system_prompt.length} characters
                    </Text>
                  </div>
                </div>
              </div>

              <Separator />

              <ToolSelector
                tools={tools}
                mcpServers={mcpServersResponse?.mcp_servers}
                enabledToolsMap={values.enabled_tools_map}
                setFieldValue={setFieldValue}
              />

              <div className="flex justify-end pt-4">
                <Button type="submit" disabled={isSubmitting}>
                  {isSubmitting ? "Saving..." : "Save Changes"}
                </Button>
              </div>
            </div>
          </Form>
        )}
      </Formik>
    </div>
  );
}

export default function Page() {
  return (
    <>
      <AdminPageTitle
        title="Default Assistant"
        icon={
          <SvgOnyxLogo
            width={32}
            height={32}
            className="my-auto stroke-text-04"
          />
        }
      />
      <DefaultAssistantConfig />
    </>
  );
}
