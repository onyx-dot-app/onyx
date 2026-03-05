import "@opal/components/Tag/styles.css";

import type { IconFunctionComponent } from "@opal/types";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TagColor = "green" | "purple" | "blue" | "gray" | "amber";

interface TagProps {
  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Tag label text. */
  title: string;

  /** Color variant. Default: `"gray"`. */
  color?: TagColor;
}

// ---------------------------------------------------------------------------
// Color config
// ---------------------------------------------------------------------------

const COLOR_CONFIG: Record<TagColor, { bg: string; text: string }> = {
  green: { bg: "bg-theme-green-01", text: "text-theme-green-05" },
  blue: { bg: "bg-theme-blue-01", text: "text-theme-blue-05" },
  purple: { bg: "bg-theme-purple-01", text: "text-theme-purple-05" },
  amber: { bg: "bg-theme-amber-01", text: "text-theme-amber-05" },
  gray: { bg: "bg-background-tint-02", text: "text-text-03" },
};

// ---------------------------------------------------------------------------
// Tag
// ---------------------------------------------------------------------------

function Tag({ icon: Icon, title, color = "gray" }: TagProps) {
  const config = COLOR_CONFIG[color];

  return (
    <div className={cn("opal-auxiliary-tag", config.bg)}>
      {Icon && (
        <div className="opal-auxiliary-tag-icon-container">
          <Icon className={cn("opal-auxiliary-tag-icon", config.text)} />
        </div>
      )}
      <span
        className={cn(
          "opal-auxiliary-tag-title px-[2px] font-figure-small-value",
          config.text
        )}
      >
        {title}
      </span>
    </div>
  );
}

export { Tag, type TagProps, type TagColor };
