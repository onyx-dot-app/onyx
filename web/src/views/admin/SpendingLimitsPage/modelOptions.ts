import type { SelectOption } from "@opal/components";
import type { SpendingLimitCard } from "@/lib/spendingLimits/types";

/** Adds the models a card already limits, in case the provider listing has
 *  not loaded them, so a saved row never shows an empty picker. */
export function withCardModels(
  options: SelectOption[],
  cards: SpendingLimitCard[]
): SelectOption[] {
  const known = new Set(options.map((option) => option.value));
  const extra: SelectOption[] = [];
  for (const card of cards) {
    for (const limit of card.limits) {
      const id = limit.model_configuration_id;
      if (id === null || known.has(String(id))) continue;
      known.add(String(id));
      extra.push({ value: String(id), title: limit.model_name ?? String(id) });
    }
  }
  return [...options, ...extra];
}
