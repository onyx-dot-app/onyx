/* eslint-disable react-hooks/static-components -- iconComponentFor is a stable name->component lookup, not a per-render component factory. */
// Maps a pure TimelineIconName to an Svg* here so state/timeline stays free of
// component imports.

import type { IconProps } from "@/components/icons/Icon";
import {
  SvgCircle,
  SvgSearchMenu,
  SvgGlobe,
  SvgTerminal,
  SvgExternalLink,
  SvgImage,
  SvgBookOpen,
  SvgUser,
  SvgSparkle,
  SvgCheckCircle,
  SvgXCircle,
  SvgFileText,
  SvgEditBig,
  SvgBranch,
  SvgFold,
  SvgExpand,
  SvgMaximize2,
  SvgStopCircle,
  SvgXOctagon,
} from "@/components/icons";
import type { TimelineIconName } from "@/state/timeline/toolDisplayHelpers";

type IconComponent = (props: IconProps) => React.ReactNode;

const ICONS: Record<TimelineIconName, IconComponent> = {
  circle: SvgCircle,
  "search-menu": SvgSearchMenu,
  globe: SvgGlobe,
  terminal: SvgTerminal,
  "external-link": SvgExternalLink,
  image: SvgImage,
  "book-open": SvgBookOpen,
  user: SvgUser,
  sparkle: SvgSparkle,
  "check-circle": SvgCheckCircle,
  "x-circle": SvgXCircle,
  "file-text": SvgFileText,
  "edit-big": SvgEditBig,
  branch: SvgBranch,
  fold: SvgFold,
  expand: SvgExpand,
  "maximize-2": SvgMaximize2,
  "stop-circle": SvgStopCircle,
  "x-octagon": SvgXOctagon,
};

export function iconComponentFor(name: TimelineIconName): IconComponent {
  return ICONS[name] ?? SvgCircle;
}

interface TimelineIconProps extends IconProps {
  name: TimelineIconName;
}

export function TimelineIcon({ name, ...props }: TimelineIconProps) {
  const Cmp = iconComponentFor(name);
  return <Cmp {...props} />;
}
