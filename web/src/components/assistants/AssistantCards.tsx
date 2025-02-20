import { Persona } from "@/app/admin/assistants/interfaces";
import { Bubble } from "@/components/Bubble";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { useSortable } from "@dnd-kit/sortable";
import React, { useState } from "react";
import { FiBookmark, FiImage, FiSearch } from "react-icons/fi";
import { MdDragIndicator } from "react-icons/md";

import { Badge } from "../ui/badge";
import { IIMAGE_GENERATION_TOOL_ID } from "@/app/chat/tools/constants";
import { SEARCH_TOOL_ID } from "@/app/chat/tools/constants";

export const AssistantCard = ({
  assistant,
  isSelected,
  onSelect,
}: {
  assistant: Persona;
  isSelected: boolean;
  onSelect: (assistant: Persona) => void;
}) => {
  const renderBadgeContent = (tool: { name: string }) => {
    switch (tool.name) {
      case SEARCH_TOOL_ID:
        return (
          <>
            <FiSearch className="h-3 w-3 my-auto" />
            <span>Search</span>
          </>
        );
      case IIMAGE_GENERATION_TOOL_ID:
        return (
          <>
            <FiImage className="h-3 w-3 my-auto" />
            <span>Image Gen</span>
          </>
        );
      default:
        return tool.name;
    }
  };

  return (
    <div
      onClick={() => onSelect(assistant)}
      className={`
        flex flex-col overflow-hidden  w-full rounded-xl px-3 py-4
        cursor-pointer
        ${isSelected ? "bg-background-125" : "hover:bg-background-100"}
      `}
    >
      <div className="flex items-center gap-4">
        <AssistantIcon size="xs" assistant={assistant} />
        <div className="overflow-hidden text-ellipsis break-words flex-grow">
          <div className="flex items-start justify-start gap-2">
            <span className="line-clamp-1 text-sm text-black font-semibold leading-tight">
              {assistant.name}
            </span>
            {assistant.tools.map((tool, index) => (
              <Badge key={index} size="xs" variant="secondary" className="ml-1">
                <div className="flex items-center gap-1">
                  {renderBadgeContent(tool)}
                </div>
              </Badge>
            ))}
          </div>
          <span className="line-clamp-2 text-xs text-text-700">
            {assistant.description}
          </span>
        </div>
      </div>
    </div>
  );
};

export function DraggableAssistantCard(props: {
  assistant: Persona;
  isSelected: boolean;
  onSelect: (assistant: Persona) => void;
  llmName: string;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: props.assistant.id.toString() });

  const style = {
    transform: transform
      ? `translate3d(${transform.x}px, ${transform.y}px, 0)`
      : undefined,
    transition,
    opacity: isDragging ? 0.9 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="overlow-y-scroll inputscroll flex items-center"
    >
      <div {...attributes} {...listeners} className="mr-1 cursor-grab">
        <MdDragIndicator className="h-3 w-3 flex-none" />
      </div>

      <AssistantCard {...props} />
    </div>
  );
}
