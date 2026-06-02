import "@opal/components/tag/styles.css";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { Text } from "@opal/components";
import { cn } from "@opal/utils";
import { TAG_COLORS, type TagColor } from "@opal/components/tag/colors";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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
// Tag
// ---------------------------------------------------------------------------

function Tag({ icon: Icon, title, color = "gray", size = "sm" }: TagProps) {
  const config = TAG_COLORS[color];

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

export { Tag, type TagProps, type TagSize };
export { TAG_COLORS, type TagColor } from "@opal/components/tag/colors";
