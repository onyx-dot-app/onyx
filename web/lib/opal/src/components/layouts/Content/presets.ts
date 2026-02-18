import type { IconFunctionComponent } from "@opal/types";

// ---------------------------------------------------------------------------
// Size presets
// ---------------------------------------------------------------------------

type SizePreset =
  | "headline"
  | "section"
  | "main-content"
  | "main-ui"
  | "secondary";

type ContentVariant = "heading" | "section" | "body";

interface SizePresetConfig {
  /** Icon width/height (CSS value). */
  iconSize: string;
  /** Tailwind padding class for the icon container. */
  iconContainerPadding: string;
  /** Gap between icon container and content (CSS value). */
  gap: string;
  /** Tailwind font class for the title. */
  titleFont: string;
  /** Title line-height — also used as icon container min-height (CSS value). */
  lineHeight: string;
  /** Button `size` prop for the edit button. */
  editButtonSize: "lg" | "md" | "sm" | "xs";
  /** Tailwind padding class for the edit button container. */
  editButtonPadding: string;
}

const SIZE_PRESETS: Record<SizePreset, SizePresetConfig> = {
  headline: {
    iconSize: "2rem",
    iconContainerPadding: "p-0.5",
    gap: "0.25rem",
    titleFont: "font-heading-h2",
    lineHeight: "2.25rem",
    editButtonSize: "md",
    editButtonPadding: "p-1",
  },
  section: {
    iconSize: "1.25rem",
    iconContainerPadding: "p-1",
    gap: "0rem",
    titleFont: "font-heading-h3",
    lineHeight: "1.75rem",
    editButtonSize: "sm",
    editButtonPadding: "p-0.5",
  },
  /* TODO (@raunakab): confirm main-content/main-ui/secondary values against Figma */
  "main-content": {
    iconSize: "1.125rem",
    iconContainerPadding: "p-[0.1875rem]",
    gap: "0.125rem",
    titleFont: "font-main-content-emphasis",
    lineHeight: "1.5rem",
    editButtonSize: "sm",
    editButtonPadding: "p-0.5",
  },
  "main-ui": {
    iconSize: "1rem",
    iconContainerPadding: "p-0.5",
    gap: "0.25rem",
    titleFont: "font-main-ui-action",
    lineHeight: "1.25rem",
    editButtonSize: "xs",
    editButtonPadding: "p-0.5",
  },
  secondary: {
    iconSize: "0.75rem",
    iconContainerPadding: "p-0.5",
    gap: "0.125rem",
    titleFont: "font-secondary-action",
    lineHeight: "1rem",
    editButtonSize: "xs",
    editButtonPadding: "p-0.5",
  },
};

// ---------------------------------------------------------------------------
// Shared base props
// ---------------------------------------------------------------------------

interface ContentBaseProps {
  /** Optional icon component. */
  icon?: IconFunctionComponent;

  /** Main heading text. */
  title: string;

  /** Optional description below the title. */
  description?: string;

  /** Enable inline editing of the title. */
  editable?: boolean;

  /** Called when the user commits an edit. */
  onTitleChange?: (newTitle: string) => void;
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export {
  SIZE_PRESETS,
  type SizePreset,
  type SizePresetConfig,
  type ContentVariant,
  type ContentBaseProps,
};
