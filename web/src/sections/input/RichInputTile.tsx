"use client";

import { cn } from "@/lib/utils";
import { getPasteTilePreview, getPasteTileMeta } from "@/lib/contentEditable";
import { SvgClipboard, SvgX } from "@opal/icons";

type RichInputTileColor = "neutral";

interface RichInputTileProps {
  text: string;
  preview?: string;
  meta?: string;
  color?: RichInputTileColor;
  onRemove?: () => void;
  onClick?: () => void;
  className?: string;
}

const COLOR_CLASS: Record<RichInputTileColor, string> = {
  neutral: "rich-input-tile",
};

function RichInputTile({
  text,
  preview,
  meta,
  color = "neutral",
  onRemove,
  onClick,
  className,
}: RichInputTileProps) {
  const displayPreview = preview ?? getPasteTilePreview(text);
  const displayMeta = meta ?? getPasteTileMeta(text);

  return (
    <span
      className={cn(COLOR_CLASS[color], className)}
      title={text.length > 200 ? text.slice(0, 200) + "…" : text}
      onClick={onClick}
    >
      <SvgClipboard size={14} className="rich-input-tile-icon" />
      <span className="rich-input-tile-preview">{displayPreview}</span>
      <span className="rich-input-tile-meta">{displayMeta}</span>
      {onRemove && (
        <span
          className="rich-input-tile-remove"
          role="button"
          aria-label="Remove pasted text"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
        >
          <SvgX size={10} />
        </span>
      )}
    </span>
  );
}

export type { RichInputTileProps, RichInputTileColor };
export default RichInputTile;
