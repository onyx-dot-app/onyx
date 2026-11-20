import type { Cache, ScopedMutator } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";

const SKILL_LIST_KEYS = [
  SWR_KEYS.userSkills,
  SWR_KEYS.chatSkills,
  SWR_KEYS.skillLimitUsers,
] as const;

/** Fetches the skill lists that a skill change can make stale: the user's
 * skills, the chat skills that the `@` menu offers, and the users past the
 * skill limit that the admin banner shows. */
export async function refreshSkillLists(mutate: ScopedMutator): Promise<void> {
  await Promise.all(SKILL_LIST_KEYS.map((key) => mutate(key)));
}

/** Refreshes the skill lists and tells whether each loaded list fetched. A
 * failed fetch does not reject SWR's `mutate`; it sets the key's error. */
export async function refreshSkillListsChecked(
  mutate: ScopedMutator,
  cache: Cache
): Promise<boolean> {
  try {
    await refreshSkillLists(mutate);
  } catch {
    return false;
  }
  return SKILL_LIST_KEYS.every((key) => cache.get(key)?.error === undefined);
}
