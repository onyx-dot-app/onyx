import type { IconFunctionComponent } from "@opal/types";
import type { InputTypeInTagProps } from "@opal/components/inputs/texts/input-type-in-tag/components";

/** A clickable row. `title`, `description` and `icon` match `Content`'s props. */
export type SelectOption = {
  value: string;
  title: string;
  description?: string;
  icon?: IconFunctionComponent;
  disabled?: boolean;
};

/**
 * A divider with the rows under it, like an `<optgroup>`. A separator line
 * sits above it, carrying `title` when there is one. Dividers render in
 * order; on a ComboBox a divider whose options all filter out disappears
 * with its line, so nothing dangles.
 */
export type SelectDivider = {
  title?: string;
  options: SelectOption[];
};

/**
 * The set: loose options and dividers in any order, like `<option>`s beside
 * `<optgroup>`s. A loose option renders as a plain row; a run of them after
 * a divider gets a plain line above it.
 */
export type SelectOptions = (SelectOption | SelectDivider)[];

/**
 * The family's trigger axis, internal to the two implementations. A
 * `"type-in"` trigger is a text input whose text filters the set (the
 * ComboBoxes); a `"button"` trigger has nothing to type and is pressed to
 * open the full set, like a native `<select>` (the Selects).
 */
export type DropdownTrigger = "type-in" | "button";

// ---------------------------------------------------------------------------
// Single arity
// ---------------------------------------------------------------------------

type InputSingleBaseProps = Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  "onChange" | "value" | "placeholder" | "readOnly"
> & {
  /** The set: loose options and titled dividers, in order. */
  options: SelectOptions;
  /** Current value */
  value: string;
  /** Called when an option is selected from the dropdown (and on a create-row commit). */
  onValueChange?: (value: string) => void;
  /** Disabled state */
  disabled?: boolean;
  /** External error state - overrides internal validation */
  isError?: boolean;
  /** Optional name for the field (for accessibility) */
  name?: string;
  /** Right content slot for custom UI elements (e.g., refresh button) */
  rightChildren?: React.ReactNode;
  /** Max height of the dropdown in CSS units. Defaults to "15rem". */
  dropdownMaxHeight?: string;
};

/**
 * `InputSingleComboBox`: a text input whose text filters the set. It takes
 * no `defaultOption`: a default would pre-fill the filter with a label the
 * user never chose, so the opened list would show only that row.
 */
export type InputSingleComboBoxProps = InputSingleBaseProps & {
  /**
   * Set openness: `"closed"` (default) permits only option values; `"open"`
   * also commits raw text via the create row.
   */
  mode?: "closed" | "open";
  /** Change handler (React event style) - called on every keystroke. */
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  /** Callback to handle validation errors - integrates with form libraries. */
  onValidationError?: (errorMessage: string | null) => void;
  /** Left search icon. */
  searchIcon?: boolean;
  /** Label for the separator between matched and unmatched options. */
  separatorLabel?: string;
  /**
   * When true, keep non-matching options visible under a separator while
   * searching. Defaults to false so search results are strictly filtered.
   */
  showOtherOptions?: boolean;
  defaultOption?: never;
  /** Trigger placeholder. */
  placeholder: string;
};

/**
 * `InputSingleSelect`: nothing to type; the trigger is pressed to open the
 * full set, like a native `<select>`. With a `defaultOption` it never reads
 * as empty: an empty `value` resolves to it, re-picking the default does
 * nothing, and re-picking any other selected option falls back to it.
 */
export type InputSingleSelectProps = InputSingleBaseProps & {
  mode?: never;
  onChange?: never;
  onValidationError?: never;
  searchIcon?: never;
  separatorLabel?: never;
  showOtherOptions?: never;
  /** The option value an empty `value` resolves to. Must be in the set. */
  defaultOption?: string;
  /**
   * Shown while empty, and always the field's accessible name, so it is
   * required even with a `defaultOption` that keeps the trigger filled.
   */
  placeholder: string;
};

/** The internal single implementation: either public prop set plus its trigger. */
export type SingleDropdownProps =
  | (InputSingleComboBoxProps & { trigger: "type-in" })
  | (InputSingleSelectProps & { trigger: "button" });

// ---------------------------------------------------------------------------
// Multi arity
// ---------------------------------------------------------------------------

type InputMultiBaseProps = Omit<
  InputTypeInTagProps,
  "value" | "onChange" | "onAdd"
> & {
  /**
   * The selectable set: loose options and titled dividers, in order.
   * Convention: a chosen option becomes a tag whose `id` is the option's
   * `value`, so the dropdown can show it selected and toggle it off.
   */
  options: SelectOptions;
  /**
   * Called when a dropdown option is chosen. Choosing an already-selected
   * option calls `onRemoveTag(option.value)` instead — one removal path.
   */
  onSelectOption: (option: SelectOption) => void;
  /** Max height of the dropdown in CSS units. Defaults to "15rem". */
  dropdownMaxHeight?: string;
};

/** `InputMultiComboBox`: chips beside a text input whose text filters the set. */
export type InputMultiComboBoxProps = InputMultiBaseProps & {
  /**
   * Set openness:
   * - "closed" (default): only options can be chosen; typing filters.
   * - "open": typing filters AND the raw text commits via the create row.
   */
  mode?: "closed" | "open";
  /** Controlled filter text. */
  value: string;
  onChange: (value: string) => void;
  /** Called with the trimmed text on a create-row commit (`mode="open"`). */
  onAdd: (value: string) => void;
};

/**
 * `InputMultiSelect`: the chips are the whole field, a focusable combobox
 * element takes the keyboard, and the list always shows the full set.
 */
export type InputMultiSelectProps = InputMultiBaseProps & {
  /** Names the combobox element, which has no text input to inherit one. */
  placeholder: string;
  mode?: never;
  value?: never;
  onChange?: never;
  onAdd?: never;
};

/** The internal multi implementation: either public prop set plus its trigger. */
export type MultiDropdownProps =
  | (InputMultiComboBoxProps & { trigger: "type-in" })
  | (InputMultiSelectProps & { trigger: "button" });
