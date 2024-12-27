import { Persona } from "@/app/admin/assistants/interfaces";
import React from "react";
import { createSVG } from "@/lib/assistantIconUtils";
import { buildImgUrl } from "@/app/chat/files/images/utils";
import { CustomTooltip } from "../tooltip/CustomTooltip";

export function darkerGenerateColorFromId(id: string): string {
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
  disableToolip,
}: {
  assistant: Persona;
  size?: "xs" | "small" | "medium" | "large" | "header";
  border?: boolean;
  disableToolip?: boolean;
}) {
  const color = darkerGenerateColorFromId(assistant.id.toString());

  return (
    <CustomTooltip
      disabled={disableToolip || !assistant.description}
      showTick
      line
      wrap
      content={assistant.description}
    >
      {
        // Prioritization order: image, graph, defaults
        assistant.uploaded_image_id ? (
          <img
            alt={assistant.name}
            className={`object-cover object-center rounded-sm overflow-hidden transition-opacity duration-300 opacity-100
              ${
                size === "large"
                  ? "w-10 h-10"
                  : size === "header"
                    ? "w-14 h-14"
                    : size === "medium"
                      ? "w-8 h-8"
                      : size === "xs"
                        ? "w-4 h-4"
                        : "w-6 h-6"
              }`}
            src={buildImgUrl(assistant.uploaded_image_id)}
            loading="lazy"
          />
        ) : assistant.icon_shape && assistant.icon_color ? (
          <div
            className={`flex-none
                  ${border && "ring ring-[1px] ring-border-strong "}
                  ${
                    size === "large"
                      ? "w-10 h-10"
                      : size === "header"
                        ? "w-14 h-14"
                        : size === "medium"
                          ? "w-8 h-8"
                          : size === "xs"
                            ? "w-4 h-4"
                            : "w-6 h-6"
                  } `}
          >
            {createSVG(
              { encodedGrid: assistant.icon_shape, filledSquares: 0 },
              assistant.icon_color,
              size === "large"
                ? 40
                : size === "header"
                  ? 56
                  : size === "medium"
                    ? 32
                    : size === "xs"
                      ? 16
                      : 24
            )}
          </div>
        ) : (
          <div
            className={`flex-none rounded-sm overflow-hidden
                  ${border && "border border-.5 border-border-strong "}
                  ${size === "large" ? "w-10 h-10" : ""}
                  ${size === "header" ? "w-14 h-14" : ""}
                  ${size === "medium" ? "w-8 h-8" : ""}
                  ${size === "xs" ? "w-4 h-4" : ""}
                  ${!size || size === "small" ? "w-6 h-6" : ""} `}
            style={{ backgroundColor: color }}
          />
        )
      }
    </CustomTooltip>
  );
}
