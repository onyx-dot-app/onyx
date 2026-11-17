import type { ScopedMutator } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";

/** Fetches the skill lists that a skill change can make stale: the user's
 * skills, the chat skills that the `@` menu offers, and the users past the
 * skill limit that the admin banner shows. */
export async function refreshSkillLists(mutate: ScopedMutator): Promise<void> {
  await Promise.all([
    mutate(SWR_KEYS.userSkills),
    mutate(SWR_KEYS.chatSkills),
    mutate(SWR_KEYS.skillLimitUsers),
  ]);
}
