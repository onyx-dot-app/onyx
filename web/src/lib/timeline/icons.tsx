import {
  SvgActions,
  SvgAlertCircle,
  SvgCheckCircle,
  SvgLightbulbSimple,
  SvgCpu,
  SvgEdit,
  SvgFileText,
  SvgGlobe,
  SvgImage,
  SvgLoader,
  SvgSearch,
  SvgSparkle,
  SvgStop,
  SvgTerminal,
} from "@opal/icons";
import type { IconFunctionComponent, IconProps } from "@opal/types";
import { cn } from "@opal/utils";

function SpinningLoader({ className, ...props }: IconProps) {
  return <SvgLoader {...props} className={cn(className, "animate-spin")} />;
}

/** The rail's step icons, one per kind of step, shared by chat and Craft. */
export const STEP_ICONS = {
  thinking: SvgLightbulbSimple,
  execute: SvgTerminal,
  search: SvgSearch,
  webSearch: SvgGlobe,
  fetch: SvgGlobe,
  edit: SvgEdit,
  read: SvgFileText,
  tool: SvgActions,
  image: SvgImage,
  agent: SvgCpu,
  skill: SvgSparkle,
  done: SvgCheckCircle,
  /** Replaces the kind's icon while the step runs. */
  running: SpinningLoader,
  /** Replaces the kind's icon when the step failed. */
  failed: SvgAlertCircle,
  /** Replaces the kind's icon when the user stopped the step. */
  stopped: SvgStop,
} as const satisfies Record<string, IconFunctionComponent>;
