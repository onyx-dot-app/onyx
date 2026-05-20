/**
 * Shared types + utilities for the `/` skill picker.
 *
 * Used by the Craft chat input (`InputBar`) and the scheduled trigger prompt
 * (`ScheduleTaskForm`). Both surfaces read the same `GET /skills` payload via
 * `useUserSkills` and feed it through `toPickerSkills` to get the picker's
 * `{ slug, name, description }` shape.
 */

import type { SkillsList } from "@/refresh-pages/admin/SkillsPage/interfaces";

export interface PickerSkill {
  slug: string;
  name: string;
  description: string;
}

/**
 * Normalize the user-facing skills payload to picker rows. The server already
 * filters to the user's accessible set; we defensively drop unavailable
 * builtins and disabled customs here too. Sorted by slug for stable ordering.
 */
export function toPickerSkills(data: SkillsList | undefined): PickerSkill[] {
  if (!data) return [];
  const builtins = data.builtins
    .filter((b) => b.is_available)
    .map((b) => ({
      slug: b.slug,
      name: b.name,
      description: b.description,
    }));
  const customs = data.customs
    .filter((c) => c.enabled)
    .map((c) => ({
      slug: c.slug,
      name: c.name,
      description: c.description,
    }));
  return [...builtins, ...customs].sort((a, b) => a.slug.localeCompare(b.slug));
}

export interface SlashTrigger {
  /** Index of the active "/" character in the full text. */
  slashIndex: number;
  /** Text typed between "/" and the cursor (exclusive of "/"). */
  query: string;
}

/**
 * Detect whether the cursor is currently inside a "/" trigger scope.
 *
 * Rules:
 * - The "/" must be at the start of the text or preceded by whitespace.
 * - Between the "/" and the cursor there must be no whitespace.
 * - The cursor must be at or after the "/" position (always true since the
 *   slash is found by lastIndexOf in `textBeforeCursor`).
 */
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

/**
 * Filter picker rows by a query string. Matches against slug, name, and
 * description (case-insensitive substring).
 */
export function filterPickerSkills(
  skills: PickerSkill[],
  query: string
): PickerSkill[] {
  const q = query.trim().toLowerCase();
  if (!q) return skills;
  return skills.filter((s) =>
    [s.slug, s.name, s.description].some((field) =>
      field.toLowerCase().includes(q)
    )
  );
}
