import { Persona } from "@/app/admin/assistants/interfaces";
import React from "react";
import { Tooltip } from "../tooltip/Tooltip";

export function generatePastelColorFromId(id: string): string {
  const hash = Array.from(id).reduce(
    (acc, char) => acc + char.charCodeAt(0),
    0
  );
  const hue = (hash * 137.508) % 360; // Use golden angle approximation
  const saturation = 70 + (hash % 10); // Saturation between 70-80%
  const lightness = 85 + (hash % 10); // Lightness between 85-95%
  return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
}

export function darkerGenerateColorFromId(id: string): string {
  if (id == "0") {
    return "#262626";
  }
  const hash = Array.from(id).reduce(
    (acc, char) => acc + char.charCodeAt(0),
    0
  );
  const hue = (hash * 137.508) % 360; // Use golden angle approximation
  // const saturation = 40 + (hash % 10); // Saturation between 40-50%
  // const lightness = 40 + (hash % 10); // Lightness between 40-50%
  const saturation = 35 + (hash % 10); // Saturation between 40-50%
  const lightness = 35 + (hash % 10); // Lightness between 40-50%

  return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
}

export function AssistantIcon({
  assistant,
  size,
  border,
}: {
  assistant: Persona;
  size?: "small" | "medium" | "large";
  border?: boolean;
}) {
  const color = darkerGenerateColorFromId(assistant.id.toString());

  return (
    <Tooltip delayDuration={1000} content={assistant.description}>
      <div
        className={`flex-none
      ${border && " border border-.5 border-border-strong "}
      ${(!size || size == "large") && "w-6 h-6"}
      ${size == "small" && "w-6 h-6"}
      rounded-lg
      `}
        style={{ backgroundColor: color }}
      />
    </Tooltip>
  );
}
