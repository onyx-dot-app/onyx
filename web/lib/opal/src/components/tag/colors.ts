// Tag color tints. Kept in a standalone, import-free module so non-React
// surfaces (e.g. the raw-DOM skill tile in richInputTile.ts) can source the same
// classes without pulling in the component/CSS barrel.

export type TagColor = "green" | "purple" | "blue" | "gray" | "amber" | "red";

export const TAG_COLORS: Record<TagColor, { bg: string; text: string }> = {
  green: { bg: "bg-theme-green-01", text: "text-theme-green-05" },
  blue: { bg: "bg-theme-blue-01", text: "text-theme-blue-05" },
  purple: { bg: "bg-theme-purple-01", text: "text-theme-purple-05" },
  amber: { bg: "bg-theme-amber-01", text: "text-theme-amber-05" },
  red: { bg: "bg-status-error-01", text: "text-status-error-05" },
  gray: { bg: "bg-background-tint-02", text: "text-text-03" },
};
