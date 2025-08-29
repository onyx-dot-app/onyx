"use client";

import {
  SlidersVerticalIcon,
  SearchIcon,
  DisableIcon,
  IconProps,
  MoreActionsIcon,
} from "@/components/icons/icons";
import React, { useState } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { useAssistantsContext } from "@/components/context/AssistantsContext";
import Link from "next/link";
import { getIconForAction } from "../../services/actionUtils";
import { useUser } from "@/components/user/UserProvider";

interface ActionItemProps {
  Icon: (iconProps: IconProps) => JSX.Element;
  label: string;
  disabled: boolean;
  isForced: boolean;
  onToggle: () => void;
  onForceToggle: () => void;
}

export function ActionItem({
  Icon,
  label,
  disabled,
  isForced,
  onToggle,
  onForceToggle,
}: ActionItemProps) {
  return (
    <div
      className={`
      group
      flex 
      items-center 
      justify-between 
      px-2 
      cursor-pointer 
      hover:bg-background-100 
      rounded-lg 
      py-2 
      mx-1
      ${isForced ? "bg-accent-100 hover:bg-accent-200" : ""}
    `}
      onClick={() => {
        // If disabled, un-disable the tool
        if (onToggle && disabled) {
          onToggle();
        }

        onForceToggle();
      }}
    >
      <div
        className={`flex items-center gap-2 flex-1 ${
          disabled ? "opacity-50" : ""
        } ${isForced && "text-blue-500"}`}
      >
        <Icon size={16} className="text-text-500" />
        <span
          className={`text-sm font-medium select-none ${
            disabled ? "line-through" : ""
          }`}
        >
          {label}
        </span>
      </div>
      <div
        className={`
          flex
          items-center
          gap-2
          transition-opacity
          duration-200
          ${disabled ? "opacity-100" : "opacity-0 group-hover:opacity-100"}
        `}
        onClick={(e) => {
          e.stopPropagation();
          onToggle();
        }}
      >
        <DisableIcon
          className={`transition-colors cursor-pointer ${
            disabled
              ? "text-text-900 hover:text-text-500"
              : "text-text-500 hover:text-text-900"
          }`}
        />
      </div>
    </div>
  );
}

export function ToolItem({
  tool,
  isToggled,
  isForced,
  onToggle,
  onForceToggle,
}: {
  tool: ToolSnapshot;
  isToggled: boolean;
  isForced: boolean;
  onToggle: () => void;
  onForceToggle: () => void;
}) {
  const Icon = getIconForAction(tool);
  return (
    <ActionItem
      Icon={Icon}
      label={tool.display_name || tool.name}
      disabled={!isToggled}
      isForced={isForced}
      onToggle={onToggle}
      onForceToggle={onForceToggle}
    />
  );
}

interface ActionToggleProps {
  selectedAssistant: MinimalPersonaSnapshot;
}

export function ActionToggle({ selectedAssistant }: ActionToggleProps) {
  const [open, setOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  // Get the assistant preference for this assistant
  const {
    assistantPreferences,
    setSpecificAssistantPreferences,
    forcedToolIds,
    setForcedToolIds,
  } = useAssistantsContext();

  const { isAdmin, isCurator } = useUser();

  const assistantPreference = assistantPreferences?.[selectedAssistant.id];
  const disabledToolIds = assistantPreference?.disabled_tool_ids || [];
  const toggleToolForCurrentAssistant = (toolId: number) => {
    const disabled = disabledToolIds.includes(toolId);
    setSpecificAssistantPreferences(selectedAssistant.id, {
      disabled_tool_ids: disabled
        ? disabledToolIds.filter((id) => id !== toolId)
        : [...disabledToolIds, toolId],
    });
  };

  const toggleForcedTool = (toolId: number) => {
    if (forcedToolIds.includes(toolId)) {
      setForcedToolIds(forcedToolIds.filter((id) => id !== toolId));
    } else {
      setForcedToolIds([...forcedToolIds, toolId]);
    }
  };

  // Filter tools based on search term
  const filteredTools = selectedAssistant.tools.filter((tool) => {
    if (!searchTerm) return true;
    const searchLower = searchTerm.toLowerCase();
    return (
      tool.display_name?.toLowerCase().includes(searchLower) ||
      tool.name.toLowerCase().includes(searchLower) ||
      tool.description?.toLowerCase().includes(searchLower)
    );
  });

  // If no tools are available, don't render the component
  if (selectedAssistant.tools.length === 0) {
    return null;
  }

  return (
    <Popover
      open={open}
      onOpenChange={(newOpen) => {
        setOpen(newOpen);
        // Clear search when closing
        if (!newOpen) {
          setSearchTerm("");
        }
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
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
          <SlidersVerticalIcon size={16} className="my-auto flex-none" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="start"
        className="
          w-[244px] 
          max-h-[300px]
          text-text-600 
          text-sm 
          p-0 
          bg-background 
          border 
          border-border 
          rounded-xl 
          shadow-xl 
          overflow-hidden
          flex
          flex-col
        "
      >
        {/* Search Input */}
        <div className="pt-1 mx-1">
          <div className="relative">
            <SearchIcon
              size={16}
              className="absolute left-3 top-1/2 transform -translate-y-1/2 text-text-400"
            />
            <input
              type="text"
              placeholder="Search Menu"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="
                w-full 
                pl-9 
                pr-3 
                py-2 
                bg-background-50 
                rounded-lg 
                text-sm 
                outline-none 
                text-text-700
                placeholder:text-text-400
              "
              autoFocus
            />
          </div>
        </div>

        {/* Options */}
        <div className="pt-2 flex-1 overflow-y-auto mx-1 pb-2">
          {filteredTools.length === 0 ? (
            <div className="text-center py-1 text-text-400">
              No matching actions found
            </div>
          ) : (
            filteredTools.map((tool) => (
              <ToolItem
                key={tool.id}
                tool={tool}
                isToggled={!disabledToolIds.includes(tool.id)}
                isForced={forcedToolIds.includes(tool.id)}
                onToggle={() => toggleToolForCurrentAssistant(tool.id)}
                onForceToggle={() => {
                  toggleForcedTool(tool.id);
                  setOpen(false);
                }}
              />
            ))
          )}
        </div>

        <div className="border-b border-border mx-3.5" />

        {/* More Connectors & Actions. Only show if user is admin or curator, since
        they are the only ones who can manage actions. */}
        {(isAdmin || isCurator) && (
          <Link href="/admin/actions">
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
              mx-2 
              mb-2 
              px-2 
              py-1.5 
              flex 
              items-center 
              hover:bg-background-100
              hover:text-text-500
              transition-colors
              rounded-lg
              w-full
            "
              >
                <MoreActionsIcon className="text-text-500" />
                <div className="ml-2">More Actions</div>
              </div>
            </button>
          </Link>
        )}
      </PopoverContent>
    </Popover>
  );
}
