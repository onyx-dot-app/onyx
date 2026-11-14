import type { Mention } from "@/lib/chat/types";
import { startsToken } from "@/lib/skills/picker";

/** Opens the chat's `@` menu; a picked mention shows as `@name` in the text. */
export const MENTION_TRIGGER = "@";

export interface PlacedMention {
  index: number;
  mention: Mention;
}

/** Each `@name` in `text` that is a whole token for one of `mentions`, in
 * text order. Text never mentions anything; this only places picked
 * mentions. */
export function findMentions(
  text: string,
  mentions: readonly Mention[]
): PlacedMention[] {
  const placed: PlacedMention[] = [];
  if (mentions.length === 0) return placed;
  for (
    let index = text.indexOf(MENTION_TRIGGER);
    index !== -1;
    index = text.indexOf(MENTION_TRIGGER, index + 1)
  ) {
    if (!startsToken(text, index)) continue;
    const mention = mentions.find(
      ({ name }) =>
        text.startsWith(name, index + 1) &&
        !/[\w-]/.test(text.charAt(index + 1 + name.length))
    );
    if (mention !== undefined) placed.push({ index, mention });
  }
  return placed;
}

/** The `mentions` whose `@name` is still in `text`, in `mentions` order. An
 * edited question keeps the recorded mentions that its new text still
 * has. */
export function mentionsInText(
  text: string,
  mentions: readonly Mention[]
): Mention[] {
  const present = new Set(
    findMentions(text, mentions).map((placed) => placed.mention)
  );
  return mentions.filter((mention) => present.has(mention));
}
