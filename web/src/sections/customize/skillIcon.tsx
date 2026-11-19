import {
  SvgBarChart,
  SvgBlocks,
  SvgBookOpen,
  SvgBracketCurly,
  SvgBranch,
  SvgBullhorn,
  SvgCalendar,
  SvgGlobe,
  SvgImage,
  SvgLightbulbSimple,
  SvgLineChartUp,
  SvgListCheck,
  SvgMail,
  SvgPaintBrush,
  SvgSearch,
  SvgServer,
  SvgShield,
  SvgSparkle,
  SvgStar,
  SvgTerminal,
  SvgTextLines,
  SvgUsers,
  SvgWorkflow,
  SvgWrench,
  SvgZap,
} from "@opal/icons";
import { ICON_TINTS, tintedIcon, type IconTint } from "@opal/components";
import type { IconFunctionComponent } from "@opal/types";
import type { Skill } from "@/lib/skills/types";

interface SkillGlyph {
  icon: IconFunctionComponent;
  tint: IconTint;
}

/** The first rule whose words appear in the skill's name or description wins. */
const RULES: readonly (SkillGlyph & { words: readonly string[] })[] = [
  {
    words: ["sql", "database", "query", "postgres", "warehouse"],
    icon: SvgServer,
    tint: "cyan",
  },
  {
    words: ["chart", "analytics", "metric", "dashboard", "kpi"],
    icon: SvgLineChartUp,
    tint: "green",
  },
  {
    words: ["report", "summary", "summarize", "status"],
    icon: SvgBarChart,
    tint: "green",
  },
  {
    words: ["release", "changelog", "pull request", "merge", "deploy"],
    icon: SvgBranch,
    tint: "purple",
  },
  {
    words: ["code", "review", "bug", "test", "api", "script"],
    icon: SvgBracketCurly,
    tint: "blue",
  },
  {
    words: ["terminal", "shell", "cli", "command"],
    icon: SvgTerminal,
    tint: "blue",
  },
  {
    words: ["design", "brand", "collateral", "slide", "deck", "pdf"],
    icon: SvgPaintBrush,
    tint: "magenta",
  },
  {
    words: ["image", "photo", "diagram", "illustration"],
    icon: SvgImage,
    tint: "magenta",
  },
  {
    words: ["mail", "email", "inbox", "reply"],
    icon: SvgMail,
    tint: "sky",
  },
  {
    words: ["announce", "marketing", "launch", "campaign", "post"],
    icon: SvgBullhorn,
    tint: "orange",
  },
  {
    words: ["standup", "daily", "weekly", "calendar", "schedule", "meeting"],
    icon: SvgCalendar,
    tint: "orange",
  },
  {
    words: ["note", "journal", "wiki", "knowledge", "learn"],
    icon: SvgBookOpen,
    tint: "amber",
  },
  {
    words: ["checklist", "task", "todo", "plan", "onboarding"],
    icon: SvgListCheck,
    tint: "amber",
  },
  {
    words: ["research", "search", "find", "lookup"],
    icon: SvgSearch,
    tint: "green",
  },
  {
    words: ["security", "compliance", "policy", "privacy", "audit"],
    icon: SvgShield,
    tint: "cyan",
  },
  {
    words: ["customer", "support", "sales", "crm", "account", "hiring"],
    icon: SvgUsers,
    tint: "sky",
  },
  {
    words: ["translate", "language", "locale", "web", "website"],
    icon: SvgGlobe,
    tint: "sky",
  },
  {
    words: ["workflow", "automate", "pipeline", "process"],
    icon: SvgWorkflow,
    tint: "purple",
  },
  {
    words: ["fix", "debug", "troubleshoot", "repair", "tool"],
    icon: SvgWrench,
    tint: "orange",
  },
  {
    words: ["write", "draft", "doc", "copy", "edit"],
    icon: SvgTextLines,
    tint: "blue",
  },
];

const FALLBACK_ICONS: readonly IconFunctionComponent[] = [
  SvgSparkle,
  SvgLightbulbSimple,
  SvgStar,
  SvgZap,
];

/** A stable number for a string, so a skill keeps its look across loads. */
function hash(text: string): number {
  let value = 0;
  for (const char of text) value = (value * 31 + char.charCodeAt(0)) >>> 0;
  return value;
}

function matches(text: string, word: string): boolean {
  return new RegExp(`(^|[^a-z])${word}`).test(text);
}

function glyphFor(
  skill: Pick<Skill, "id" | "name" | "description">
): SkillGlyph {
  const name = skill.name.replace(/[-_]/g, " ").toLowerCase();
  const description = skill.description.toLowerCase();
  const rule =
    RULES.find((candidate) =>
      candidate.words.some((word) => matches(name, word))
    ) ??
    RULES.find((candidate) =>
      candidate.words.some((word) => matches(description, word))
    );
  if (rule) return rule;
  const seed = hash(skill.id);
  return {
    icon: FALLBACK_ICONS[seed % FALLBACK_ICONS.length] ?? SvgSparkle,
    tint: ICON_TINTS[seed % ICON_TINTS.length] ?? "blue",
  };
}

/** The icon of a skill: a built-in keeps the plain skill icon, and a custom
 * skill gets a coloured glyph that fits its name or description. */
export function skillIcon(skill: Skill): IconFunctionComponent {
  if (skill.source === "builtin") return SvgBlocks;
  const glyph = glyphFor(skill);
  return tintedIcon(glyph.icon, glyph.tint);
}
