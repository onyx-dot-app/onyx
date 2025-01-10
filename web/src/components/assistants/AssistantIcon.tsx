import React from "react";
import crypto from "crypto";
import { Persona } from "@/app/admin/assistants/interfaces";
import { CustomTooltip } from "../tooltip/CustomTooltip";
import { buildImgUrl } from "@/app/chat/files/images/utils";
import { OnyxIcon } from "../icons/icons";

type IconSize = number | "xs" | "small" | "medium" | "large" | "header";

function md5ToBits(str: string): number[] {
  const md5hex = crypto.createHash("md5").update(str).digest("hex");
  const bits: number[] = [];
  for (let i = 0; i < md5hex.length; i += 2) {
    const byteVal = parseInt(md5hex.substring(i, i + 2), 16);
    for (let b = 7; b >= 0; b--) {
      bits.push((byteVal >> b) & 1);
    }
  }
  return bits;
}

export function generateIdenticon(str: string, dimension: number) {
  const bits = md5ToBits(str);
  const gridSize = 5;
  const halfCols = 4;
  const cellSize = dimension / gridSize;

  let bitIndex = 0;
  const squares: JSX.Element[] = [];

  for (let row = 0; row < gridSize; row++) {
    for (let col = 0; col < halfCols; col++) {
      const bit = bits[bitIndex % bits.length];
      bitIndex++;

      if (bit === 1) {
        const xPos = col * cellSize;
        const yPos = row * cellSize;
        squares.push(
          <rect
            key={`${xPos}-${yPos}`}
            x={xPos - 0.5}
            y={yPos - 0.5}
            width={cellSize + 1}
            height={cellSize + 1}
            fill="black"
          />
        );

        const mirrorCol = gridSize - 1 - col;
        if (mirrorCol !== col) {
          const mirrorX = mirrorCol * cellSize;
          squares.push(
            <rect
              key={`a-${mirrorX}-${yPos}`}
              x={mirrorX - 0.5}
              y={yPos - 0.5}
              width={cellSize + 1}
              height={cellSize + 1}
              fill="black"
            />
          );
        }
      }
    }
  }

  return (
    <svg
      width={dimension}
      height={dimension}
      viewBox={`0 0 ${dimension} ${dimension}`}
      style={{ display: "block" }}
    >
      {squares}
    </svg>
  );
}

export function AssistantIcon({
  assistant,
  size,
  border,
  className,
  disableToolip,
}: {
  assistant: Persona;
  size?: IconSize;
  className?: string;
  border?: boolean;
  disableToolip?: boolean;
}) {
  const dimension =
    typeof size === "number"
      ? size
      : (() => {
          switch (size) {
            case "xs":
              return 16;
            case "small":
              return 24;
            case "medium":
              return 32;
            case "large":
              return 40;
            case "header":
              return 56;
            default:
              return 24;
          }
        })();

  const wrapperClass = border ? "ring ring-[1px] ring-border-strong" : "";
  const style = { width: dimension, height: dimension };

  return (
    <CustomTooltip
      className={className}
      disabled={disableToolip || !assistant.description}
      showTick
      line
      wrap
      content={assistant.description}
    >
      {assistant.id == 0 ? (
        <OnyxIcon size={dimension} />
      ) : assistant.uploaded_image_id ? (
        <img
          alt={assistant.name}
          src={buildImgUrl(assistant.uploaded_image_id)}
          loading="lazy"
          className={`object-cover object-center rounded-sm transition-opacity duration-300 ${wrapperClass}`}
          style={style}
        />
      ) : (
        <div className={wrapperClass} style={style}>
          {generateIdenticon((assistant.icon_shape || 0).toString(), dimension)}
        </div>
      )}
    </CustomTooltip>
  );
}
