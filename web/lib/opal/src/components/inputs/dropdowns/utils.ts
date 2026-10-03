import type {
  DropdownItem,
  DropdownOption,
} from "@opal/components/dropdown/types";
import type {
  SelectOption,
  SelectOptions,
} from "@opal/components/inputs/dropdowns/types";

/** The family's `options` prop as `Dropdown.Data` items. */
export function toDropdownItems(options: SelectOptions = []): DropdownItem[] {
  return options.map((entry) =>
    "options" in entry
      ? entry.title !== undefined
        ? {
            kind: "group",
            title: entry.title,
            foldable: entry.foldable,
            items: entry.options.map(toDropdownOption),
          }
        : { kind: "group", items: entry.options.map(toDropdownOption) }
      : toDropdownOption(entry)
  );
}

export function toDropdownOption(option: SelectOption): DropdownOption {
  // `kind` last: an option carrying a stray `kind` must still be an option.
  return { ...option, kind: "option" };
}

/** Flat option list in render order, dividers unwrapped. */
export function flattenOptions(options: SelectOptions = []): SelectOption[] {
  return options.flatMap((entry) =>
    "options" in entry ? entry.options : [entry]
  );
}
