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
import type { IconFunctionComponent, IconProps } from "@opal/types";
import { cn } from "@opal/utils";
import type { Skill } from "@/lib/skills/types";

/** Theme strokes, half mixed with the neutral icon colour so they stay quiet.
 * The `!` wins over the row's interactive icon colour. */
const TINTS = [
  "stroke-[color-mix(in_srgb,var(--theme-blue-05)_45%,var(--text-03))]!",
  "stroke-[color-mix(in_srgb,var(--theme-green-05)_45%,var(--text-03))]!",
  "stroke-[color-mix(in_srgb,var(--theme-purple-05)_45%,var(--text-03))]!",
  "stroke-[color-mix(in_srgb,var(--theme-amber-05)_45%,var(--text-03))]!",
  "stroke-[color-mix(in_srgb,var(--theme-cyan-05)_45%,var(--text-03))]!",
  "stroke-[color-mix(in_srgb,var(--theme-magenta-05)_45%,var(--text-03))]!",
  "stroke-[color-mix(in_srgb,var(--theme-orange-05)_45%,var(--text-03))]!",
  "stroke-[color-mix(in_srgb,var(--theme-sky-05)_45%,var(--text-03))]!",
] as const;

type Tint = (typeof TINTS)[number];

interface SkillGlyph {
  icon: IconFunctionComponent;
  tint: Tint;
}

/** The first rule whose words appear in the skill's name or description wins. */
const RULES: readonly (SkillGlyph & { words: readonly string[] })[] = [
  {
    words: ["sql", "database", "query", "postgres", "warehouse"],
    icon: SvgServer,
    tint: "stroke-[color-mix(in_srgb,var(--theme-cyan-05)_45%,var(--text-03))]!",
  },
  {
    words: ["chart", "analytics", "metric", "dashboard", "kpi"],
    icon: SvgLineChartUp,
    tint: "stroke-[color-mix(in_srgb,var(--theme-green-05)_45%,var(--text-03))]!",
  },
  {
    words: ["report", "summary", "summarize", "status"],
    icon: SvgBarChart,
    tint: "stroke-[color-mix(in_srgb,var(--theme-green-05)_45%,var(--text-03))]!",
  },
  {
    words: ["release", "changelog", "pull request", "merge", "deploy"],
    icon: SvgBranch,
    tint: "stroke-[color-mix(in_srgb,var(--theme-purple-05)_45%,var(--text-03))]!",
  },
  {
    words: ["code", "review", "bug", "test", "api", "script"],
    icon: SvgBracketCurly,
    tint: "stroke-[color-mix(in_srgb,var(--theme-blue-05)_45%,var(--text-03))]!",
  },
  {
    words: ["terminal", "shell", "cli", "command"],
    icon: SvgTerminal,
    tint: "stroke-[color-mix(in_srgb,var(--theme-blue-05)_45%,var(--text-03))]!",
  },
  {
    words: ["design", "brand", "collateral", "slide", "deck", "pdf"],
    icon: SvgPaintBrush,
    tint: "stroke-[color-mix(in_srgb,var(--theme-magenta-05)_45%,var(--text-03))]!",
  },
  {
    words: ["image", "photo", "diagram", "illustration"],
    icon: SvgImage,
    tint: "stroke-[color-mix(in_srgb,var(--theme-magenta-05)_45%,var(--text-03))]!",
  },
  {
    words: ["mail", "email", "inbox", "reply"],
    icon: SvgMail,
    tint: "stroke-[color-mix(in_srgb,var(--theme-sky-05)_45%,var(--text-03))]!",
  },
  {
    words: ["announce", "marketing", "launch", "campaign", "post"],
    icon: SvgBullhorn,
    tint: "stroke-[color-mix(in_srgb,var(--theme-orange-05)_45%,var(--text-03))]!",
  },
  {
    words: ["standup", "daily", "weekly", "calendar", "schedule", "meeting"],
    icon: SvgCalendar,
    tint: "stroke-[color-mix(in_srgb,var(--theme-orange-05)_45%,var(--text-03))]!",
  },
  {
    words: ["note", "journal", "wiki", "knowledge", "learn"],
    icon: SvgBookOpen,
    tint: "stroke-[color-mix(in_srgb,var(--theme-amber-05)_45%,var(--text-03))]!",
  },
  {
    words: ["checklist", "task", "todo", "plan", "onboarding"],
    icon: SvgListCheck,
    tint: "stroke-[color-mix(in_srgb,var(--theme-amber-05)_45%,var(--text-03))]!",
  },
  {
    words: ["research", "search", "find", "lookup"],
    icon: SvgSearch,
    tint: "stroke-[color-mix(in_srgb,var(--theme-green-05)_45%,var(--text-03))]!",
  },
  {
    words: ["security", "compliance", "policy", "privacy", "audit"],
    icon: SvgShield,
    tint: "stroke-[color-mix(in_srgb,var(--theme-cyan-05)_45%,var(--text-03))]!",
  },
  {
    words: ["customer", "support", "sales", "crm", "account", "hiring"],
    icon: SvgUsers,
    tint: "stroke-[color-mix(in_srgb,var(--theme-sky-05)_45%,var(--text-03))]!",
  },
  {
    words: ["translate", "language", "locale", "web", "website"],
    icon: SvgGlobe,
    tint: "stroke-[color-mix(in_srgb,var(--theme-sky-05)_45%,var(--text-03))]!",
  },
  {
    words: ["workflow", "automate", "pipeline", "process"],
    icon: SvgWorkflow,
    tint: "stroke-[color-mix(in_srgb,var(--theme-purple-05)_45%,var(--text-03))]!",
  },
  {
    words: ["fix", "debug", "troubleshoot", "repair", "tool"],
    icon: SvgWrench,
    tint: "stroke-[color-mix(in_srgb,var(--theme-orange-05)_45%,var(--text-03))]!",
  },
  {
    words: ["write", "draft", "doc", "copy", "edit"],
    icon: SvgTextLines,
    tint: "stroke-[color-mix(in_srgb,var(--theme-blue-05)_45%,var(--text-03))]!",
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
    tint:
      TINTS[seed % TINTS.length] ??
      "stroke-[color-mix(in_srgb,var(--theme-blue-05)_45%,var(--text-03))]!",
  };
}

const tinted = new Map<
  IconFunctionComponent,
  Map<Tint, IconFunctionComponent>
>();

function tintedIcon({ icon: Icon, tint }: SkillGlyph): IconFunctionComponent {
  const byTint = tinted.get(Icon) ?? new Map<Tint, IconFunctionComponent>();
  tinted.set(Icon, byTint);
  const cached = byTint.get(tint);
  if (cached) return cached;
  function TintedSkillIcon({ className, ...props }: IconProps) {
    return <Icon {...props} className={cn(className, tint)} />;
  }
  byTint.set(tint, TintedSkillIcon);
  return TintedSkillIcon;
}

/** The icon of a skill: a built-in keeps the plain skill icon, and a custom
 * skill gets a coloured glyph that fits its name or description. */
export function skillIcon(skill: Skill): IconFunctionComponent {
  return skill.source === "builtin" ? SvgBlocks : tintedIcon(glyphFor(skill));
}
