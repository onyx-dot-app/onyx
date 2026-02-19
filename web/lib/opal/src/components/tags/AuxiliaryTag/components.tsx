import "@opal/components/tags/AuxiliaryTag/styles.css";

import type { IconFunctionComponent } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type AuxiliaryTagColor = "green" | "purple" | "blue" | "gray" | "amber";

interface AuxiliaryTagProps {
  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Tag label text. */
  title: string;

  /** Color variant. Default: `"gray"`. */
  color?: AuxiliaryTagColor;
}

// ---------------------------------------------------------------------------
// Color config
// ---------------------------------------------------------------------------

const COLOR_CONFIG: Record<AuxiliaryTagColor, { bg: string; text: string }> = {
  green: { bg: "bg-theme-green-01", text: "text-theme-green-05" },
  blue: { bg: "bg-theme-blue-05", text: "text-theme-blue-01" },
  purple: { bg: "bg-theme-purple-05", text: "text-theme-purple-01" },
  amber: { bg: "bg-theme-amber-05", text: "text-theme-amber-01" },
  gray: { bg: "bg-background-tint-02", text: "text-text-03" },
};

// ---------------------------------------------------------------------------
// AuxiliaryTag
// ---------------------------------------------------------------------------

function AuxiliaryTag({
  icon: Icon,
  title,
  color = "gray",
}: AuxiliaryTagProps) {
  const config = COLOR_CONFIG[color];

  return (
    <div className={`opal-auxiliary-tag ${config.bg}`}>
      {Icon && (
        <div className="opal-auxiliary-tag-icon-container">
          <Icon className={`opal-auxiliary-tag-icon ${config.text}`} />
        </div>
      )}
      <span
        className={`opal-auxiliary-tag-title font-figure-small-value ${config.text}`}
      >
        {title}
      </span>
    </div>
  );
}

export { AuxiliaryTag, type AuxiliaryTagProps, type AuxiliaryTagColor };
