import type { ScopedMutator } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";

/** Fetches the skill lists that a skill change can make stale: the user's
 * skills and the chat skills that the `@` menu offers. */
export async function refreshSkillLists(mutate: ScopedMutator): Promise<void> {
  await Promise.all([mutate(SWR_KEYS.userSkills), mutate(SWR_KEYS.chatSkills)]);
}
