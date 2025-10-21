"use client";

import { useState, useEffect } from "react";
import { ThreeDotsLoader } from "@/components/Loading";
import { useRouter } from "next/navigation";
import { AdminPageTitle } from "@/components/admin/Title";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Text from "@/refresh-components/texts/Text";
import useSWR, { mutate } from "swr";
import { ErrorCallout } from "@/components/ErrorCallout";
import OnyxLogo from "@/icons/onyx-logo";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { SubLabel } from "@/components/Field";
import Button from "@/refresh-components/buttons/Button";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface DefaultAssistantConfiguration {
  tool_ids: number[];
  system_prompt: string;
}

interface DefaultAssistantUpdateRequest {
  tool_ids?: number[];
  system_prompt?: string;
}

interface AvailableTool {
  id: number;
  in_code_tool_id: string;
  display_name: string;
  description: string;
  is_available: boolean;
}

// Tools are now fetched from the backend dynamically

function DefaultAssistantConfig() {
  const router = useRouter();
  const { popup, setPopup } = usePopup();
  const { refreshAgents } = useAgentsContext();
  const [savingTools, setSavingTools] = useState<Set<number>>(new Set());
  const [savingPrompt, setSavingPrompt] = useState(false);
  const [enabledTools, setEnabledTools] = useState<Set<number>>(new Set());
  const [systemPrompt, setSystemPrompt] = useState<string>("");
  const [originalPrompt, setOriginalPrompt] = useState<string>("");
  const { data: availableTools } = useSWR<AvailableTool[]>(
    "/api/admin/default-assistant/available-tools",
    errorHandlingFetcher
  );

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
      setOriginalPrompt(config.system_prompt);
    }
  }, [config]);

  const persistConfiguration = async (
    updates: DefaultAssistantUpdateRequest
  ) => {
    // Avoid trailing slash to prevent 307 redirect (breaks CORS in CI)
    const response = await fetch("/api/admin/default-assistant", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    if (!response.ok) {
      throw new Error("Failed to update assistant");
    }
  };

  const handleToggleTool = async (toolId: number) => {
    const next = new Set(enabledTools);
    if (next.has(toolId)) {
      next.delete(toolId);
    } else {
      next.add(toolId);
    }
    setEnabledTools(next);
    setSavingTools((prev) => new Set(prev).add(toolId));

    try {
      await persistConfiguration({ tool_ids: Array.from(next) });
      await mutate("/api/admin/default-assistant/configuration");
      router.refresh();
      await refreshAgents();
    } catch (e) {
      const rollback = new Set(enabledTools);
      if (rollback.has(toolId)) {
        rollback.delete(toolId);
      } else {
        rollback.add(toolId);
      }
      setEnabledTools(rollback);
      setPopup({ message: "Failed to save. Please try again.", type: "error" });
    } finally {
      setSavingTools((prev) => {
        const updated = new Set(prev);
        updated.delete(toolId);
        return updated;
      });
    }
  };

  const handleSystemPromptChange = (value: string) => {
    setSystemPrompt(value);
  };

  const handleSaveSystemPrompt = async () => {
    if (systemPrompt === originalPrompt) return;

    setSavingPrompt(true);
    const currentPrompt = systemPrompt;

    try {
      await persistConfiguration({ system_prompt: currentPrompt });
      await mutate("/api/admin/default-assistant/configuration");
      router.refresh();
      await refreshAgents();
      setOriginalPrompt(currentPrompt);
      setPopup({
        message: "Instructions updated successfully!",
        type: "success",
      });
    } catch (error) {
      setSystemPrompt(originalPrompt);
      setPopup({
        message: "Failed to update instructions",
        type: "error",
      });
    } finally {
      setSavingPrompt(false);
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
      <div className="space-y-6">
        <div className="mt-4">
          <Text className="text-text-dark">
            Configure which capabilities are enabled for the default assistant
            in chat. These settings apply to all users who haven&apos;t
            customized their assistant preferences.
          </Text>
        </div>

        <Separator />

        <div className="max-w-4xl">
          <div className="flex gap-x-2 items-center">
            <Text mainUiBody text04 className="font-medium text-sm">
              Instructions
            </Text>
          </div>
          <SubLabel>
            Add instructions to tailor the behavior of the assistant.
          </SubLabel>
          <div>
            <textarea
              className={cn(
                "w-full",
                "p-3",
                "border",
                "border-border",
                "rounded-lg",
                "text-sm",
                "[&::placeholder]:text-text-muted/50"
              )}
              rows={8}
              value={systemPrompt}
              onChange={(e) => handleSystemPromptChange(e.target.value)}
              placeholder="You are a professional email writing assistant that always uses a polite enthusiastic tone, emphasizes action items, and leaves blanks for the human to fill in when you have unknowns"
            />
            <div className="flex justify-between items-center mt-2">
              <Text mainUiMuted text03 className="text-sm">
                {systemPrompt.length} characters
              </Text>
              <Button
                onClick={handleSaveSystemPrompt}
                disabled={savingPrompt || systemPrompt === originalPrompt}
              >
                {savingPrompt ? "Saving..." : "Save Instructions"}
              </Button>
            </div>
          </div>
        </div>

        <Separator />

        <div>
          <Text mainUiBody text04 className="font-medium text-sm mb-2">
            Actions
          </Text>
          <div className="space-y-3">
            {(availableTools || [])
              .slice()
              .sort((a, b) => {
                // Show enabled (available) tools first; not enabled at bottom
                if (a.is_available === b.is_available) return 0;
                return a.is_available ? -1 : 1;
              })
              .map((tool) => (
                <ToolToggle
                  key={tool.id}
                  tool={tool}
                  enabled={enabledTools.has(tool.id)}
                  onToggle={() => handleToggleTool(tool.id)}
                  disabled={savingTools.has(tool.id)}
                />
              ))}
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
    id: number;
    in_code_tool_id: string;
    display_name: string;
    description: string;
    is_available: boolean;
  };
  enabled: boolean;
  onToggle: () => void;
  disabled?: boolean;
}) {
  const notEnabledReason = (() => {
    if (tool.in_code_tool_id === "WebSearchTool") {
      return "Set EXA_API_KEY on the server and restart to enable Web Search.";
    }
    if (tool.in_code_tool_id === "ImageGenerationTool") {
      return "Add an OpenAI LLM provider with an API key under Admin → Configuration → LLM.";
    }
    return "Not configured.";
  })();
  return (
    <div className="flex items-center justify-between p-3 rounded-lg border border-border">
      <div className="flex-1 pr-4">
        <div className="text-sm font-medium flex items-center gap-2">
          <span>{tool.display_name}</span>
          {!tool.is_available && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="text-xs text-text-400 border border-border rounded px-1 py-0.5 cursor-help">
                  Not enabled
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <Text inverted>{notEnabledReason}</Text>
              </TooltipContent>
            </Tooltip>
          )}
        </div>
        <Text className="text-sm text-text-600 mt-1">{tool.description}</Text>
      </div>
      <Switch
        checked={enabled}
        onCheckedChange={() => {
          if (tool.is_available) {
            onToggle();
          }
        }}
        disabled={disabled || !tool.is_available}
      />
    </div>
  );
}

export default function Page() {
  return (
    <div className="w-full max-w-4xl mr-auto">
      <AdminPageTitle
        title="Default Assistant"
        icon={
          <OnyxLogo width={32} height={32} className="my-auto stroke-text-04" />
        }
      />
      <DefaultAssistantConfig />
    </div>
  );
}
