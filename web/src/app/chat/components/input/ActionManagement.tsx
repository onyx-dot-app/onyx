import {
  SlidersVerticalIcon,
  SearchIcon,
  GlobeIcon,
  ImageIcon,
  CpuIcon,
  ChevronRightIcon,
  UsersIcon,
  DatabaseIcon,
} from "@/components/icons/icons";
import React, { useState, useEffect, useRef } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ChatInputOption } from "./ChatInputOption";
import { Switch } from "@/components/ui/switch";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { ToolSnapshot } from "@/lib/tools/interfaces";

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

interface ActionToggleProps {
  selectedAssistant: MinimalPersonaSnapshot;
}

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

export function ActionToggle({ selectedAssistant }: ActionToggleProps) {
  const [open, setOpen] = useState(false);

  // Check which tools are available for this assistant
  const hasSearchTool = selectedAssistant.tools.some(isSearchTool);
  const hasWebSearchTool = selectedAssistant.tools.some(isWebSearchTool);
  const hasImageGenerationTool = selectedAssistant.tools.some(
    isImageGenerationTool
  );
  const hasKnowledgeGraphTool =
    selectedAssistant.tools.some(isKnowledgeGraphTool);
  const hasOktaProfileTool = selectedAssistant.tools.some(isOktaProfileTool);

  // Get custom tools (tools that aren't one of the built-in ones)
  const customTools = selectedAssistant.tools.filter(
    (tool) =>
      !isSearchTool(tool) &&
      !isWebSearchTool(tool) &&
      !isImageGenerationTool(tool) &&
      !isKnowledgeGraphTool(tool) &&
      !isOktaProfileTool(tool)
  );

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
          {hasSearchTool && (
            <ActionItem
              icon={<SearchIcon size={16} className="text-default" />}
              label="App Search"
              defaultChecked={true}
              onToggle={(checked) =>
                console.log("File Search toggled:", checked)
              }
            />
          )}

          {hasWebSearchTool && (
            <ActionItem
              icon={<GlobeIcon size={16} className="text-default" />}
              label="Web Search"
              defaultChecked={true}
              onToggle={(checked) =>
                console.log("Web Search toggled:", checked)
              }
            />
          )}

          {hasImageGenerationTool && (
            <ActionItem
              icon={<ImageIcon size={16} className="text-default" />}
              label="Image Generation"
              defaultChecked={false}
              onToggle={(checked) =>
                console.log("Image Generation toggled:", checked)
              }
            />
          )}

          {hasKnowledgeGraphTool && (
            <ActionItem
              icon={<DatabaseIcon size={16} className="text-default" />}
              label="Knowledge Graph"
              defaultChecked={true}
              onToggle={(checked) =>
                console.log("Knowledge Graph toggled:", checked)
              }
            />
          )}

          {hasOktaProfileTool && (
            <ActionItem
              icon={<UsersIcon size={16} className="text-default" />}
              label="Okta Profile"
              defaultChecked={true}
              onToggle={(checked) =>
                console.log("Okta Profile toggled:", checked)
              }
            />
          )}

          {/* Render custom tools */}
          {customTools.map((tool) => (
            <ActionItem
              key={tool.id}
              icon={<CpuIcon size={16} className="text-default" />}
              label={tool.display_name || tool.name}
              defaultChecked={true}
              onToggle={(checked) =>
                console.log(`${tool.display_name} toggled:`, checked)
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
            <span className="ml-2">More Connectors & Actions</span>
          </div>
        </button>
      </PopoverContent>
    </Popover>
  );
}
