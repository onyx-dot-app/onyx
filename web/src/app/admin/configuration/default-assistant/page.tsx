"use client";

import { useState, useEffect } from "react";
import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Text from "@/components/ui/text";
import useSWR, { mutate } from "swr";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ChatIcon } from "@/components/icons/icons";
import { usePopup } from "@/components/admin/connectors/Popup";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { SubLabel } from "@/components/Field";

interface DefaultAssistantConfiguration {
  tool_ids: string[];
  system_prompt: string;
}

interface DefaultAssistantUpdateRequest {
  tool_ids?: string[];
  system_prompt?: string;
}

// Hardcoded tool definitions for the frontend
const AVAILABLE_TOOLS = [
  {
    id: "SearchTool",
    display_name: "Document Search",
    description:
      "Enable searching through connected documents and knowledge sources",
  },
  {
    id: "InternetSearchTool",
    display_name: "Web Search",
    description:
      "Enable web search for current information and online resources",
  },
  {
    id: "ImageGenerationTool",
    display_name: "Image Generation",
    description: "Enable AI image generation based on text descriptions",
  },
];

function DefaultAssistantConfig() {
  const { popup, setPopup } = usePopup();
  const [isSaving, setIsSaving] = useState(false);
  const [enabledTools, setEnabledTools] = useState<Set<string>>(new Set());
  const [systemPrompt, setSystemPrompt] = useState<string>("");

  // Fetch default assistant configuration
  const {
    data: config,
    isLoading,
    error,
  } = useSWR<DefaultAssistantConfiguration>(
    "/api/admin/default-assistant/configuration",
    errorHandlingFetcher
  );

  // Initialize state when config loads
  useEffect(() => {
    if (config) {
      setEnabledTools(new Set(config.tool_ids));
      setSystemPrompt(config.system_prompt);
    }
  }, [config]);

  const persistConfiguration = async (
    updates: DefaultAssistantUpdateRequest
  ) => {
    const response = await fetch("/api/admin/default-assistant/", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    if (!response.ok) {
      throw new Error("Failed to update assistant");
    }
  };

  const handleToggleTool = async (toolId: string) => {
    if (isSaving) return;
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
      await persistConfiguration({ tool_ids: Array.from(next) });
      await mutate("/api/admin/default-assistant/configuration");
    } catch (e) {
      setEnabledTools(previous);
      setPopup({ message: "Failed to save. Please try again.", type: "error" });
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveSystemPrompt = async () => {
    setIsSaving(true);
    try {
      await persistConfiguration({ system_prompt: systemPrompt });
      await mutate("/api/admin/default-assistant/configuration");
      setPopup({
        message: "System prompt updated successfully!",
        type: "success",
      });
    } catch (error) {
      setPopup({
        message: "Failed to update system prompt",
        type: "error",
      });
    } finally {
      setIsSaving(false);
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

  return (
    <div>
      {popup}
      <div className="max-w-4xl w-full">
        <div className="space-y-6">
          <div className="mt-4">
            <Text className="text-text-dark">
              Configure which capabilities are enabled for the default assistant
              in chat. These settings apply to all users who haven&apos;t
              customized their assistant preferences.
            </Text>
          </div>

          <Separator />

          <div>
            <p className="block font-medium text-sm">Instructions</p>
            <SubLabel>
              Add instructions to tailor the behavior of the assistant.
            </SubLabel>
            <div>
              <textarea
                className="w-full p-3 border border-border rounded-lg resize-none"
                rows={8}
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="Enter custom instructions for the assistant..."
                disabled={isSaving}
              />
            </div>
          </div>

          <Separator />

          <div>
            <p className="block font-medium text-sm mb-2">Actions</p>
            <div className="space-y-3">
              {AVAILABLE_TOOLS.map((tool) => (
                <ToolToggle
                  key={tool.id}
                  tool={tool}
                  enabled={enabledTools.has(tool.id)}
                  onToggle={() => handleToggleTool(tool.id)}
                  disabled={isSaving}
                />
              ))}
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
  disabled,
}: {
  tool: {
    id: string;
    display_name: string;
    description: string;
  };
  enabled: boolean;
  onToggle: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between p-3 rounded-lg border border-border">
      <div className="flex-1 pr-4">
        <div className="text-sm font-medium">{tool.display_name}</div>
        <Text className="text-sm text-text-600 mt-1">{tool.description}</Text>
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
    <div className="mx-auto max-w-4xl w-full">
      <AdminPageTitle
        title="Default Assistant"
        icon={<ChatIcon size={32} className="my-auto" />}
      />
      <DefaultAssistantConfig />
    </div>
  );
}
