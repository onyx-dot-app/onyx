"use client";

import { useState, useEffect } from "react";
import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { Button } from "@/components/ui/button";
import useSWR, { mutate } from "swr";
import { ErrorCallout } from "@/components/ErrorCallout";
import { AssistantsIconSkeleton } from "@/components/icons/icons";
import CardSection from "@/components/admin/CardSection";
import { Persona } from "@/lib/types";
import { FiCheck, FiX } from "react-icons/fi";
import { usePopup } from "@/components/admin/connectors/Popup";

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
  const { data: personas, isLoading: isLoadingPersonas } = useSWR<Persona[]>(
    "/api/persona",
    errorHandlingFetcher
  );

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

  const handleToggleTool = (toolId: number) => {
    setEnabledTools((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(toolId)) {
        newSet.delete(toolId);
      } else {
        newSet.add(toolId);
      }
      return newSet;
    });
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

      <Title className="mb-2 !text-2xl">Default Assistant Configuration</Title>
      <Text className="mb-6">
        Configure which capabilities are enabled for the default assistant.
        These settings apply to all users who haven't customized their assistant
        preferences.
      </Text>

      <CardSection>
        <div className="space-y-6">
          <div>
            <Title className="mb-4 !text-lg">Assistant Details</Title>
            <div className="space-y-2">
              <div>
                <Text className="font-semibold">Name:</Text>
                <Text className="text-text-700">{defaultAssistant.name}</Text>
              </div>
              <div>
                <Text className="font-semibold">Description:</Text>
                <Text className="text-text-700">
                  {defaultAssistant.description}
                </Text>
              </div>
            </div>
          </div>

          <div>
            <Title className="mb-4 !text-lg">Available Capabilities</Title>
            <div className="space-y-4">
              {searchTool && (
                <ToolToggle
                  tool={searchTool}
                  enabled={enabledTools.has(searchTool.id)}
                  onToggle={() => handleToggleTool(searchTool.id)}
                  description="Enable searching through connected documents and knowledge sources"
                />
              )}

              {internetSearchTool && (
                <ToolToggle
                  tool={internetSearchTool}
                  enabled={enabledTools.has(internetSearchTool.id)}
                  onToggle={() => handleToggleTool(internetSearchTool.id)}
                  description="Enable web search for current information and online resources"
                />
              )}

              {imageGenerationTool && (
                <ToolToggle
                  tool={imageGenerationTool}
                  enabled={enabledTools.has(imageGenerationTool.id)}
                  onToggle={() => handleToggleTool(imageGenerationTool.id)}
                  description="Enable AI image generation based on text descriptions"
                />
              )}
            </div>
          </div>
        </div>
      </CardSection>

      <div className="mt-6 flex gap-2">
        <Button onClick={handleSave} disabled={isSaving}>
          {isSaving ? "Saving..." : "Save Configuration"}
        </Button>
      </div>
    </div>
  );
}

function ToolToggle({
  tool,
  enabled,
  onToggle,
  description,
}: {
  tool: Tool;
  enabled: boolean;
  onToggle: () => void;
  description: string;
}) {
  return (
    <div className="flex items-start space-x-4 p-4 rounded-lg border border-border">
      <button
        onClick={onToggle}
        className={`mt-1 flex h-6 w-6 items-center justify-center rounded-md transition-colors ${
          enabled
            ? "bg-success-500 text-white"
            : "bg-background-100 border border-border-300"
        }`}
      >
        {enabled ? <FiCheck size={16} /> : <FiX size={16} />}
      </button>
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <Text className="font-semibold">{tool.display_name}</Text>
          <span
            className={`px-2 py-0.5 rounded text-xs font-medium ${
              enabled
                ? "bg-success-100 text-success-700"
                : "bg-background-100 text-text-500"
            }`}
          >
            {enabled ? "Enabled" : "Disabled"}
          </span>
        </div>
        <Text className="text-sm text-text-600 mt-1">{description}</Text>
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Default Assistant"
        icon={<AssistantsIconSkeleton size={32} className="my-auto" />}
      />
      <DefaultAssistantConfig />
    </div>
  );
}
