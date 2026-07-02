import type {
  ExternalAppType,
  ExternalAppUserResponse,
} from "@/app/craft/v1/apps/registry";
import type { SkillsList } from "@/lib/skills/types";

export interface PickerSkill {
  kind: "skill";
  slug: string;
  name: string;
  description: string;
}

export interface PickerApp {
  kind: "app";
  slug: string;
  name: string;
  description: string;
  appType: ExternalAppType;
  authenticated: boolean;
}

export type PickerEntry = PickerSkill | PickerApp;

export interface PickerSections {
  skills: PickerSkill[];
  apps: PickerApp[];
}

const EMPTY_SECTIONS: PickerSections = { skills: [], apps: [] };

// `/api/skills` omits external-app-backed skills; the Apps section is built
// from `/api/build/apps` instead.
export function toPickerSections(
  skillsData: SkillsList | undefined,
  externalApps: ExternalAppUserResponse[] | undefined
): PickerSections {
  if (!skillsData && !externalApps) return EMPTY_SECTIONS;

  const skills: PickerSkill[] = [];
  const apps: PickerApp[] = [];

  for (const b of skillsData?.builtins ?? []) {
    if (!b.is_available) continue;
    skills.push({
      kind: "skill",
      slug: b.slug,
      name: b.name,
      description: b.description,
    });
  }

  for (const c of skillsData?.customs ?? []) {
    if (!c.enabled) continue;
    skills.push({
      kind: "skill",
      slug: c.slug,
      name: c.name,
      description: c.description,
    });
  }

  for (const app of externalApps ?? []) {
    apps.push({
      kind: "app",
      slug: app.slug,
      name: app.name,
      description: app.description,
      appType: app.app_type,
      authenticated: app.authenticated,
    });
  }

  skills.sort((a, b) => a.slug.localeCompare(b.slug));
  apps.sort((a, b) => a.slug.localeCompare(b.slug));

  return { skills, apps };
}

export interface SlashTrigger {
  slashIndex: number;
  query: string;
}

// Trigger rules: "/" must be at start-of-text or after whitespace; the query
// (chars between "/" and the cursor) must not contain whitespace.
export function detectSlashTrigger(
  textBeforeCursor: string
): SlashTrigger | null {
  const slashIndex = textBeforeCursor.lastIndexOf("/");
  if (slashIndex === -1) return null;

  if (slashIndex > 0) {
    const prev = textBeforeCursor[slashIndex - 1] ?? "";
    if (!/\s/.test(prev)) return null;
  }

  const query = textBeforeCursor.slice(slashIndex + 1);
  if (/\s/.test(query)) return null;

  return { slashIndex, query };
}

function matchesQuery(entry: PickerEntry, query: string): boolean {
  if (!query) return true;
  return [entry.slug, entry.name, entry.description].some((field) =>
    field.toLowerCase().includes(query)
  );
}

export function filterPickerSections(
  sections: PickerSections,
  query: string
): PickerSections {
  const q = query.trim().toLowerCase();
  if (!q) return sections;
  return {
    skills: sections.skills.filter((s) => matchesQuery(s, q)),
    apps: sections.apps.filter((a) => matchesQuery(a, q)),
  };
}

// Skills first, then apps; must match the popover's visual render order so
// keyboard nav indices line up.
export function flattenSections(sections: PickerSections): PickerEntry[] {
  return [...sections.skills, ...sections.apps];
}
