"use client";

import React, { useRef, useEffect, useMemo, useState } from "react";
import {
  SlashCommand,
  SlashCommandType,
} from "@/app/chat/components/slash-commands/types";
import LineItem from "@/refresh-components/buttons/LineItem";
import { PopoverMenu } from "@/components/ui/popover";
import SvgBubbleText from "@/icons/bubble-text";
import SvgArrowRight from "@/icons/arrow-right";
import SvgPlug from "@/icons/plug";
import SvgChevronRight from "@/icons/chevron-right";
import SvgChevronDown from "@/icons/chevron-down";
import Text from "@/refresh-components/texts/Text";

interface SlashCommandMenuProps {
  commands: SlashCommand[];
  selectedIndex: number;
  onSelect: (command: SlashCommand) => void;
}

const GROUP_LABELS: Record<SlashCommandType, string> = {
  prompt: "Prompts",
  navigation: "Navigation",
  tool: "Tools",
};

const GROUP_ICONS: Record<SlashCommandType, React.ReactNode> = {
  prompt: <SvgBubbleText size={14} />,
  navigation: <SvgArrowRight size={14} />,
  tool: <SvgPlug size={14} />,
};

const GROUP_ORDER: SlashCommandType[] = ["tool", "navigation", "prompt"];

export default function SlashCommandMenu({
  commands,
  selectedIndex,
  onSelect,
}: SlashCommandMenuProps) {
  const itemRefs = useRef<(HTMLDivElement | null)[]>([]);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Track which groups are expanded (default to all expanded)
  const [expandedGroups, setExpandedGroups] = useState<Set<SlashCommandType>>(
    new Set(GROUP_ORDER)
  );

  // Group commands by type
  const groupedCommands = useMemo(() => {
    const groups = commands.reduce(
      (acc, cmd) => {
        if (!acc[cmd.type]) {
          acc[cmd.type] = [];
        }
        acc[cmd.type].push(cmd);
        return acc;
      },
      {} as Record<SlashCommandType, SlashCommand[]>
    );

    // Return groups in the defined order
    return GROUP_ORDER.filter((type) => groups[type]?.length > 0).map(
      (type) => ({
        type,
        label: GROUP_LABELS[type],
        commands: groups[type],
      })
    );
  }, [commands]);

  useEffect(() => {
    const selectedItem = itemRefs.current[selectedIndex];
    if (selectedItem) {
      selectedItem.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [selectedIndex]);

  const toggleGroup = (type: SlashCommandType) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  };

  if (commands.length === 0) return null;

  let flatIndex = 0;

  return (
    <div className="absolute left-0 top-0 transform -translate-y-full mb-1">
      <div className="bg-background-neutral-00 p-1.5 rounded-12 border shadow-md max-h-[500px] overflow-hidden w-[280px] flex flex-col gap-2">
        {/* Title */}
        <Text secondaryBody text03 className="px-2">
          Commands
        </Text>

        {/* Scrollable content */}
        <PopoverMenu
          scrollContainerRef={scrollContainerRef}
          medium
          className="!w-full"
        >
          {groupedCommands.map((group, groupIdx) => {
            const isExpanded = expandedGroups.has(group.type);

            return (
              <div key={group.type}>
                {/* Group header - collapsible */}
                {groupedCommands.length > 1 && (
                  <button
                    onClick={() => toggleGroup(group.type)}
                    className="w-full px-1.5 py-1 flex items-center gap-1.5 text-xs font-medium text-text-03 rounded-08 hover:bg-background-tint-02 transition-colors"
                  >
                    <div className="flex items-center justify-center size-5 shrink-0">
                      {GROUP_ICONS[group.type]}
                    </div>
                    <span className="flex-1 text-left">{group.label}</span>
                    <div className="flex items-center justify-center size-6 shrink-0">
                      {isExpanded ? (
                        <SvgChevronDown className="h-4 w-4 stroke-text-04" />
                      ) : (
                        <SvgChevronRight className="h-4 w-4 stroke-text-04" />
                      )}
                    </div>
                  </button>
                )}

                {/* Group commands - only show when expanded */}
                {isExpanded && (
                  <>
                    {group.commands.map((command) => {
                      const currentIndex = flatIndex++;
                      const isNewPromptCommand =
                        command.command === "/new-prompt";

                      return (
                        <div
                          key={command.command}
                          ref={(el) => {
                            itemRefs.current[currentIndex] = el;
                          }}
                        >
                          {isNewPromptCommand ? (
                            <div className="mt-2">
                              <button
                                onClick={() => onSelect(command)}
                                className="px-2 py-1 flex items-center gap-1.5 text-xs font-medium text-text-03 bg-background-neutral-01 hover:bg-background-neutral-02 rounded-08 border border-border-01 transition-colors"
                              >
                                <span className="text-sm">+</span>
                                <span>New prompt</span>
                              </button>
                            </div>
                          ) : (
                            <div className="[&_p]:text-left">
                              <LineItem
                                selected={selectedIndex === currentIndex}
                                emphasized={selectedIndex === currentIndex}
                                description={command.description}
                                onClick={() => onSelect(command)}
                              >
                                {command.command}
                              </LineItem>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </>
                )}

                {/* Divider between groups (except after last group) */}
                {groupIdx < groupedCommands.length - 1 && (
                  <div className="my-1 border-t border-border-01" />
                )}
              </div>
            );
          })}
        </PopoverMenu>
      </div>
    </div>
  );
}
