"use client";

import { useState, useEffect } from "react";
import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import useSWR, { mutate } from "swr";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ChatIcon } from "@/components/icons/icons";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { usePopup } from "@/components/admin/connectors/Popup";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";

interface Tool {
  id: number;
  name: string;
  display_name: string;
  description: string | null;
  in_code_tool_id: string | null;
}

function DefaultAssistantConfig() {
  const { popup, setPopup } = usePopup();
  const [isSaving, setIsSaving] = useState(false);
  const [enabledTools, setEnabledTools] = useState<Set<number>>(new Set());

  // Fetch all personas
  const { data: personas, isLoading: isLoadingPersonas } = useSWR<
    MinimalPersonaSnapshot[]
  >("/api/persona", errorHandlingFetcher);

  // Fetch all available tools
  const { data: tools, isLoading: isLoadingTools } = useSWR<Tool[]>(
    "/api/tool",
    errorHandlingFetcher
  );

  // Find the default assistant (ID 0 or first with is_default_persona)
  const defaultAssistant = personas?.find(
    (p) => p.id === 0 || p.is_default_persona
  );

  // Initialize enabled tools when data loads
  useEffect(() => {
    if (defaultAssistant?.tools) {
      setEnabledTools(new Set(defaultAssistant.tools.map((t) => t.id)));
    }
  }, [defaultAssistant]);

  const persistEnabledTools = async (toolIds: number[]) => {
    if (!defaultAssistant) return;
    const response = await fetch(`/api/persona/${defaultAssistant.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tool_ids: toolIds }),
    });
    if (!response.ok) {
      throw new Error("Failed to update assistant");
    }
  };

  const handleToggleTool = async (toolId: number) => {
    if (!defaultAssistant || isSaving) return;
    setIsSaving(true);
    const previous = new Set(enabledTools);
    const next = new Set(enabledTools);
    if (next.has(toolId)) {
      next.delete(toolId);
    } else {
      next.add(toolId);
    }
    setEnabledTools(next);
    try {
      await persistEnabledTools(Array.from(next));
      await mutate("/api/persona");
    } catch (e) {
      setEnabledTools(previous);
      setPopup({ message: "Failed to save. Please try again.", type: "error" });
    } finally {
      setIsSaving(false);
    }
  };

  const handleSave = async () => {
    if (!defaultAssistant) return;

    setIsSaving(true);
    try {
      const response = await fetch(`/api/persona/${defaultAssistant.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          tool_ids: Array.from(enabledTools),
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to update assistant");
      }

      // Refresh the personas data
      await mutate("/api/persona");

      setPopup({
        message: "Default assistant configuration updated successfully!",
        type: "success",
      });
    } catch (error) {
      setPopup({
        message: "Failed to update assistant configuration",
        type: "error",
      });
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoadingPersonas || isLoadingTools) {
    return <ThreeDotsLoader />;
  }

  if (!defaultAssistant) {
    return (
      <ErrorCallout
        errorTitle="No default assistant found"
        errorMsg="Unable to find the default assistant in the system."
      />
    );
  }

  // Filter for built-in tools only
  const builtInTools = tools?.filter((tool) => tool.in_code_tool_id) || [];

  // Organize tools by type
  const searchTool = builtInTools.find(
    (t) => t.in_code_tool_id === "SearchTool"
  );
  const internetSearchTool = builtInTools.find(
    (t) => t.in_code_tool_id === "InternetSearchTool"
  );
  const imageGenerationTool = builtInTools.find(
    (t) => t.in_code_tool_id === "ImageGenerationTool"
  );

  return (
    <div>
      {popup}
      <div className="max-w-4xl w-full">
        <div className="space-y-6">
          <div>
            <p className="text-base font-normal text-2xl">Default Assistant</p>
            <Text className="mb-2 text-text-dark">
              Configure which capabilities are enabled for the default assistant
              in chat. These settings apply to all users who haven&apos;t
              customized their assistant preferences.
            </Text>
          </div>

          <Separator />

          <div>
            <p className="block font-medium text-sm mb-2">
              Available Capabilities
            </p>
            <div className="space-y-3">
              {searchTool && (
                <ToolToggle
                  tool={searchTool}
                  enabled={enabledTools.has(searchTool.id)}
                  onToggle={() => handleToggleTool(searchTool.id)}
                  description="Enable searching through connected documents and knowledge sources"
                  disabled={isSaving}
                />
              )}

              {internetSearchTool && (
                <ToolToggle
                  tool={internetSearchTool}
                  enabled={enabledTools.has(internetSearchTool.id)}
                  onToggle={() => handleToggleTool(internetSearchTool.id)}
                  description="Enable web search for current information and online resources"
                  disabled={isSaving}
                />
              )}

              {imageGenerationTool && (
                <ToolToggle
                  tool={imageGenerationTool}
                  enabled={enabledTools.has(imageGenerationTool.id)}
                  onToggle={() => handleToggleTool(imageGenerationTool.id)}
                  description="Enable AI image generation based on text descriptions"
                  disabled={isSaving}
                />
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ToolToggle({
  tool,
  enabled,
  onToggle,
  description,
  disabled,
}: {
  tool: Tool;
  enabled: boolean;
  onToggle: () => void;
  description: string;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between p-3 rounded-lg border border-border">
      <div className="flex-1 pr-4">
        <div className="text-sm font-medium">{tool.display_name}</div>
        <Text className="text-sm text-text-600 mt-1">{description}</Text>
      </div>
      <Switch
        checked={enabled}
        onCheckedChange={onToggle}
        disabled={disabled}
      />
    </div>
  );
}

export default function Page() {
  return (
    <div className="mx-auto max-w-4xl">
      <AdminPageTitle
        title="Chat Settings"
        icon={<ChatIcon size={32} className="my-auto" />}
      />
      <DefaultAssistantConfig />
    </div>
  );
}
