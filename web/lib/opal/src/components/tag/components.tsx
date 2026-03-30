import "@opal/components/tag/styles.css";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { Text } from "@opal/components";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TagColor = "green" | "purple" | "blue" | "gray" | "amber";

type TagSize = "sm" | "md";

interface TagProps {
  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Tag label text. */
  title: string | RichStr;

  /** Color variant. Default: `"gray"`. */
  color?: TagColor;

  /** Size variant. Default: `"sm"`. */
  size?: TagSize;
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

function Tag({ icon: Icon, title, color = "gray", size = "sm" }: TagProps) {
  const config = COLOR_CONFIG[color];

  return (
    <div
      className={cn("opal-auxiliary-tag", config.bg, config.text)}
      data-size={size}
    >
      {Icon && (
        <div className="opal-auxiliary-tag-icon-container">
          <Icon className={cn("opal-auxiliary-tag-icon", config.text)} />
        </div>
      )}
      <Text
        font={size === "md" ? "secondary-body" : "figure-small-value"}
        color="inherit"
        nowrap
      >
        {title}
      </Text>
    </div>
  );
}

export { Tag, type TagProps, type TagColor, type TagSize };
