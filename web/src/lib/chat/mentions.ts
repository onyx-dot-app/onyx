import {
  MAX_MENTIONS_PER_MESSAGE,
  type ComposedMention,
  type Mention,
  type PlacedMention,
} from "@/lib/chat/types";
import type { PickerSections } from "@/lib/skills/picker";

/** Opens the chat's `@` menu; a picked mention shows as `@name` in the text. */
export const MENTION_TRIGGER = "@";

/** The `@` menu's match: the skills whose name starts with the query,
 * ignoring case. */
export function filterMentionEntries(
  entries: PickerSections,
  query: string
): PickerSections {
  const prefix = query.toLowerCase();
  return {
    ...entries,
    skills: entries.skills.filter((skill) =>
      skill.name.toLowerCase().startsWith(prefix)
    ),
  };
}

/** Where each mention's tile goes in `text`, in text order. A mention with
 * an `index` stays there when `text` has its `@name` there. Any other mention
 * takes the first `@name` that no other tile holds, wherever it is in a word,
 * so a recorded mention keeps its tile beside `(` or a word typed against it.
 * Longer names go first, so `@code` never takes the start of `@code-review`.
 * Each mention gets at most one tile, and one whose `@name` is gone gets
 * none. Text never mentions anything; this only places picked mentions. */
export function placeMentions(
  text: string,
  mentions: readonly ComposedMention[]
): PlacedMention[] {
  const placed: PlacedMention[] = [];
  const isFree = (index: number, length: number) =>
    placed.every(
      (tile) =>
        index + length <= tile.index ||
        tile.index + MENTION_TRIGGER.length + tile.name.length <= index
    );
  const unplaced: ComposedMention[] = [];
  for (const mention of mentions) {
    const token = `${MENTION_TRIGGER}${mention.name}`;
    if (
      mention.index !== undefined &&
      text.startsWith(token, mention.index) &&
      isFree(mention.index, token.length)
    )
      placed.push({
        type: mention.type,
        name: mention.name,
        index: mention.index,
      });
    else unplaced.push(mention);
  }
  unplaced.sort((a, b) => b.name.length - a.name.length);
  for (const mention of unplaced) {
    const token = `${MENTION_TRIGGER}${mention.name}`;
    let index = text.indexOf(token);
    while (index !== -1 && !isFree(index, token.length))
      index = text.indexOf(token, index + 1);
    if (index !== -1)
      placed.push({ type: mention.type, name: mention.name, index });
  }
  return placed.sort((a, b) => a.index - b.index);
}

/** The mentions a request sends: each one once, in order, without its
 * place in the text, and only the first `MAX_MENTIONS_PER_MESSAGE`. The send
 * and pending-message requests call it, so every entry path is bounded. */
export function requestMentions(
  mentions: readonly ComposedMention[]
): Mention[] {
  const unique = new Map<string, Mention>();
  for (const { type, name } of mentions) {
    if (unique.size === MAX_MENTIONS_PER_MESSAGE) break;
    if (!unique.has(`${type}:${name}`))
      unique.set(`${type}:${name}`, { type, name });
  }
  return [...unique.values()];
}
