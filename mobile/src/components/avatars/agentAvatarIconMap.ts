import type { IconFunctionComponent } from "@/icons/types";
import SvgActivitySmall from "@/icons/activity-small";
import SvgAudioEqSmall from "@/icons/audio-eq-small";
import SvgBarChartSmall from "@/icons/bar-chart-small";
import SvgBooksLineSmall from "@/icons/books-line-small";
import SvgBooksStackSmall from "@/icons/books-stack-small";
import SvgCheckSmall from "@/icons/check-small";
import SvgClockHandsSmall from "@/icons/clock-hands-small";
import SvgFileSmall from "@/icons/file-small";
import SvgHashSmall from "@/icons/hash-small";
import SvgImageSmall from "@/icons/image-small";
import SvgInfoSmall from "@/icons/info-small";
import SvgMusicSmall from "@/icons/music-small";
import SvgPenSmall from "@/icons/pen-small";
import SvgQuestionMarkSmall from "@/icons/question-mark-small";
import SvgSearchSmall from "@/icons/search-small";
import SvgSlidersSmall from "@/icons/sliders-small";
import SvgTerminalSmall from "@/icons/terminal-small";
import SvgTextLinesSmall from "@/icons/text-lines-small";

interface AgentIconConfig {
  Icon: IconFunctionComponent;
  // text-* class → Icon color → SVG stroke=currentColor (light/dark via vars()).
  colorClass: string;
}

// Maps the backend icon_name (exact, case-sensitive) to its icon + color. Unknown/absent →
// monogram → two-line glyph (see AgentAvatar).
export const AGENT_AVATAR_ICON_MAP: Record<string, AgentIconConfig> = {
  Info: { Icon: SvgInfoSmall, colorClass: "text-theme-primary-05" },
  QuestionMark: {
    Icon: SvgQuestionMarkSmall,
    colorClass: "text-theme-primary-05",
  },
  TextLines: { Icon: SvgTextLinesSmall, colorClass: "text-theme-blue-05" },
  Pen: { Icon: SvgPenSmall, colorClass: "text-theme-blue-05" },
  ClockHands: { Icon: SvgClockHandsSmall, colorClass: "text-theme-blue-05" },
  Hash: { Icon: SvgHashSmall, colorClass: "text-theme-blue-05" },
  Search: { Icon: SvgSearchSmall, colorClass: "text-theme-green-05" },
  Check: { Icon: SvgCheckSmall, colorClass: "text-theme-green-05" },
  BarChart: { Icon: SvgBarChartSmall, colorClass: "text-theme-green-05" },
  Activity: { Icon: SvgActivitySmall, colorClass: "text-theme-green-05" },
  File: { Icon: SvgFileSmall, colorClass: "text-theme-purple-05" },
  Image: { Icon: SvgImageSmall, colorClass: "text-theme-purple-05" },
  BooksStack: { Icon: SvgBooksStackSmall, colorClass: "text-theme-purple-05" },
  BooksLine: { Icon: SvgBooksLineSmall, colorClass: "text-theme-purple-05" },
  Terminal: { Icon: SvgTerminalSmall, colorClass: "text-theme-orange-04" },
  Sliders: { Icon: SvgSlidersSmall, colorClass: "text-theme-orange-04" },
  AudioEq: { Icon: SvgAudioEqSmall, colorClass: "text-theme-amber-04" },
  Music: { Icon: SvgMusicSmall, colorClass: "text-theme-amber-04" },
};
