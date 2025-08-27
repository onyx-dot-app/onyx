import {
  SlidersVerticalIcon,
  SearchIcon,
  GlobeIcon,
  ImageIcon,
  CpuIcon,
  UsersIcon,
  DatabaseIcon,
} from "@/components/icons/icons";
import React, { useState } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Switch } from "@/components/ui/switch";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { useAssistantsContext } from "@/components/context/AssistantsContext";
import Link from "next/link";

// Helper functions to identify specific tools
const isSearchTool = (tool: ToolSnapshot): boolean => {
  return (
    tool.in_code_tool_id === "SearchTool" ||
    tool.name === "run_search" ||
    tool.display_name?.toLowerCase().includes("search tool")
  );
};

const isWebSearchTool = (tool: ToolSnapshot): boolean => {
  return (
    tool.in_code_tool_id === "InternetSearchTool" ||
    tool.display_name?.toLowerCase().includes("internet search")
  );
};

const isImageGenerationTool = (tool: ToolSnapshot): boolean => {
  return (
    tool.in_code_tool_id === "ImageGenerationTool" ||
    tool.display_name?.toLowerCase().includes("image generation")
  );
};

const isKnowledgeGraphTool = (tool: ToolSnapshot): boolean => {
  return (
    tool.in_code_tool_id === "KnowledgeGraphTool" ||
    tool.display_name?.toLowerCase().includes("knowledge graph")
  );
};

const isOktaProfileTool = (tool: ToolSnapshot): boolean => {
  return (
    tool.in_code_tool_id === "OktaProfileTool" ||
    tool.display_name?.toLowerCase().includes("okta profile")
  );
};

interface ActionItemProps {
  icon: React.ReactNode;
  label: string;
  defaultChecked?: boolean;
  onToggle?: (checked: boolean) => void;
}

export function ActionItem({
  icon,
  label,
  defaultChecked = false,
  onToggle,
}: ActionItemProps) {
  return (
    <div
      className="
      flex 
      items-center 
      justify-between 
      px-2 
      cursor-pointer 
      hover:bg-background-150 
      rounded-lg 
      py-2 
      mx-1
    "
    >
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-sm font-medium">{label}</span>
      </div>
      <div className="flex items-center gap-2">
        <Switch
          defaultChecked={defaultChecked}
          onCheckedChange={onToggle}
          className="data-[state=checked]:bg-blue-500 dark:data-[state=checked]:bg-white"
          size="sm"
        />
      </div>
    </div>
  );
}

export function ToolItem({
  tool,
  isToggled,
  onToggle,
}: {
  tool: ToolSnapshot;
  isToggled: boolean;
  onToggle: (checked: boolean) => void;
}) {
  let icon: React.ReactNode;
  if (isSearchTool(tool)) {
    icon = <SearchIcon size={16} className="text-default" />;
  } else if (isWebSearchTool(tool)) {
    icon = <GlobeIcon size={16} className="text-default" />;
  } else if (isImageGenerationTool(tool)) {
    icon = <ImageIcon size={16} className="text-default" />;
  } else if (isKnowledgeGraphTool(tool)) {
    icon = <DatabaseIcon size={16} className="text-default" />;
  } else if (isOktaProfileTool(tool)) {
    icon = <UsersIcon size={16} className="text-default" />;
  } else {
    icon = <CpuIcon size={16} className="text-default" />;
  }

  return (
    <ActionItem
      icon={icon}
      label={tool.display_name || tool.name}
      defaultChecked={isToggled}
      onToggle={onToggle}
    />
  );
}

interface ActionToggleProps {
  selectedAssistant: MinimalPersonaSnapshot;
}

export function ActionToggle({ selectedAssistant }: ActionToggleProps) {
  const [open, setOpen] = useState(false);

  // Get the assistant preference for this assistant
  const { assistantPreferences, setSpecificAssistantPreferences } =
    useAssistantsContext();

  const assistantPreference = assistantPreferences?.[selectedAssistant.id];
  const disabledToolIds = assistantPreference?.disabled_tool_ids || [];
  const toggleToolForCurrentAssistant = (toolId: number, enabled: boolean) => {
    setSpecificAssistantPreferences(selectedAssistant.id, {
      disabled_tool_ids: enabled
        ? disabledToolIds.filter((id) => id !== toolId)
        : [...disabledToolIds, toolId],
    });
  };

  // If no tools are available, don't render the component
  if (selectedAssistant.tools.length === 0) {
    return null;
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          className="
            relative 
            cursor-pointer 
            flex 
            items-center 
            group 
            rounded-lg 
            text-input-text 
            hover:bg-background-chat-hover 
            hover:text-neutral-900 
            dark:hover:text-neutral-50 
            py-1.5 
            px-2 
            flex-none 
            whitespace-nowrap 
            overflow-hidden 
            focus:outline-none
          "
          data-testid="action-popover-trigger"
          title={open ? undefined : "Configure actions"}
        >
          <SlidersVerticalIcon
            size={16}
            className="h-4 w-4 my-auto flex-none"
          />
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="start"
        className="
          w-[244px] 
          max-h-[240px]
          text-text-600 
          text-sm 
          p-0 
          bg-background 
          border 
          border-border 
          rounded-xl 
          shadow-xl 
          overflow-hidden
        "
      >
        {/* Options */}
        <div className="pt-2">
          {selectedAssistant.tools.map((tool) => (
            <ToolItem
              key={tool.id}
              tool={tool}
              isToggled={!disabledToolIds.includes(tool.id)}
              onToggle={(checked) =>
                toggleToolForCurrentAssistant(tool.id, checked)
              }
            />
          ))}
        </div>

        {/* More Connectors & Actions */}
        <button
          className="
            w-full 
            flex 
            items-center 
            justify-between 
            text-text-400
            text-sm
            mt-2.5
          "
        >
          <div
            className="
              mx-1 
              mb-2 
              px-2.5 
              py-1.5 
              flex 
              items-center 
              hover:bg-background-150
              hover:text-text-500
              transition-colors
              rounded-lg
              w-full
            "
          >
            <svg
              className="w-4 h-4 text-default"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"
              />
            </svg>
            <Link href="/admin/actions" className="ml-2">
              More Connectors & Actions
            </Link>
          </div>
        </button>
      </PopoverContent>
    </Popover>
  );
}
