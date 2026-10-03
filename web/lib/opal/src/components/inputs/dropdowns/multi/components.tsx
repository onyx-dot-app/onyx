"use client";

import { useCallback, useEffect, useId, useMemo, useRef } from "react";
import { useOpalStrings } from "@opal/strings";
import {
  TagField,
  type TagItem,
} from "@opal/components/inputs/texts/input-type-in-tag/TagField";
import { Dropdown } from "@opal/components/dropdown/components";
import { useDropdownContext } from "@opal/components/dropdown/context";
import type {
  DropdownItem,
  DropdownOption,
} from "@opal/components/dropdown/types";
import { SelectChevron } from "@opal/components/inputs/dropdowns/SelectChevron";
import {
  flattenOptions,
  toDropdownItems,
} from "@opal/components/inputs/dropdowns/utils";
import type { MultiDropdownProps } from "../types";

// ---------------------------------------------------------------------------
// MultiDropdown
// ---------------------------------------------------------------------------

/**
 * MultiDropdown — the multi-arity implementation behind the family's two
 * public components. Internal to Opal; app code uses `InputMultiSelect`
 * (button trigger) or `InputMultiComboBox` (type-in trigger).
 *
 * `InputTypeInTag`'s chips-in-input chrome on `@opal/Dropdown`. Chosen
 * options render as Tags. With a `"type-in"` trigger typing filters the
 * option set; with a `"button"` trigger there is no text input and the
 * chips are the whole field. Free tagging with no set to pick from is
 * `InputTypeInTag` itself.
 *
 * The `TagField` renders its own input, out of `Dropdown.Trigger`'s reach,
 * so this engine wires the trigger through the dropdown's context.
 */
function MultiDropdown(props: MultiDropdownProps) {
  const autoId = useId();
  const fieldId = `multi-select-${autoId}`;
  return (
    <Dropdown id={fieldId} disabled={props.disabled ?? false}>
      <MultiDropdownField {...props} />
    </Dropdown>
  );
}

function MultiDropdownField(props: MultiDropdownProps) {
  const {
    tags,
    onRemoveTag,
    options: optionsProp,
    onSelectOption,
    placeholder,
    variant = "primary",
    disabled = false,
    icon,
    onClear,
    minRows,
    maxRows,
    focusOnMount,
    dropdownMaxHeight,
  } = props;
  const strings = useOpalStrings();
  const typeIn = props.trigger !== "button";
  const search = props.trigger === "button" && (props.search ?? false);
  // A button trigger has no text: an empty filter, and nothing to commit.
  const value = props.value ?? "";
  const onChange = props.onChange;
  const onAdd = props.onAdd;
  const mode = props.mode ?? "closed";

  const {
    isOpen,
    setIsOpen,
    setHighlightedIndex,
    setIsKeyboardNav,
    setAnchorRef,
    setTriggerRef,
    focusTrigger,
    getTriggerProps,
  } = useDropdownContext();

  // A button trigger has no input: its combobox element takes the focus
  // and the keyboard.
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setTriggerRef(typeIn ? inputRef.current : triggerRef.current);
  }, [typeIn, setTriggerRef]);

  const flatOptions = useMemo(() => flattenOptions(optionsProp), [optionsProp]);
  const freeEntry = typeIn && mode === "open";

  const selectedValues = useMemo(
    () => new Set(tags.map((tag) => tag.id)),
    [tags]
  );

  // A chip shows its option's icon (by the tag id = option value
  // convention) unless the caller set one on the tag itself.
  const iconTags = useMemo<TagItem[]>(() => {
    const iconByValue = new Map(
      flatOptions.map((option) => [option.value, option.icon])
    );
    return tags.map((tag) =>
      tag.icon ? tag : { ...tag, icon: iconByValue.get(tag.id) }
    );
  }, [tags, flatOptions]);

  // Free-form tags (open mode, outside the set) appear in the dropdown as
  // real, selected rows — the single's custom row — so re-picking one
  // routes through the toggle-off instead of the create row. They form
  // their own group, so a line separates them from the set.
  const items = useMemo<DropdownItem[]>(() => {
    const set = toDropdownItems(optionsProp);
    if (!freeEntry) return set;
    const optionValues = new Set(flatOptions.map((option) => option.value));
    const custom = tags
      .filter((tag) => !optionValues.has(tag.id))
      .map<DropdownOption>((tag) => ({
        kind: "option",
        value: tag.id,
        title: tag.label,
      }));
    if (custom.length === 0) return set;
    return [{ kind: "group", items: custom }, ...set];
  }, [optionsProp, freeEntry, flatOptions, tags]);

  // Closed-set doctrine, committed values only: a tag outside the supplied
  // set (stale seed, options shrank) flags the input chrome's error variant.
  // Open mode legitimately holds free-form tags, and typing never flags. A
  // locked tag is fixed by the caller, not picked, so it never flags.
  const hasInvalidTag = useMemo(() => {
    if (freeEntry) return false;
    const optionValues = new Set(flatOptions.map((option) => option.value));
    return tags.some((tag) => !tag.locked && !optionValues.has(tag.id));
  }, [freeEntry, flatOptions, tags]);

  // The filter is transient UI state, like the single's: closing the
  // dropdown drops whatever was typed (the caller owns the text, so the
  // component clears it through onChange).
  // Only the open→closed transition acts; other dep changes just no-op.
  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (typeIn && wasOpenRef.current && !isOpen && value !== "") onChange?.("");
    wasOpenRef.current = isOpen;
  }, [typeIn, isOpen, value, onChange]);

  const filterText = typeIn ? value : "";
  const hasSearchTerm = filterText.trim() !== "";
  const trimmedValue = value.trim().toLowerCase();
  // An exact match means Enter should pick the option — or nothing, when
  // the text already exists as a chip — never fork a duplicate.
  const exactOptionMatch =
    flatOptions.some(
      (option) =>
        option.value.toLowerCase() === trimmedValue ||
        option.title.toLowerCase() === trimmedValue
    ) ||
    tags.some(
      (tag) =>
        tag.id.toLowerCase() === trimmedValue ||
        tag.label.toLowerCase() === trimmedValue
    );
  const showCreateOption = freeEntry && hasSearchTerm && !exactOptionMatch;

  const handleOptionSelect = useCallback(
    (option: DropdownOption) => {
      if (option.disabled) return;
      const real = flatOptions.find((o) => o.value === option.value);
      if (real) {
        if (selectedValues.has(real.value)) {
          onRemoveTag(real.value);
        } else {
          onSelectOption(real);
        }
      } else if (selectedValues.has(option.value)) {
        // A free-form tag's own row: toggle it off.
        onRemoveTag(option.value);
      }
      // Stay open for further picks; reset the filter.
      onChange?.("");
      focusTrigger();
    },
    [
      flatOptions,
      selectedValues,
      onRemoveTag,
      onSelectOption,
      onChange,
      focusTrigger,
    ]
  );

  // The create row: commit the raw text as a free-form tag.
  const handleCreate = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (trimmed) onAdd?.(trimmed);
      onChange?.("");
      focusTrigger();
    },
    [onAdd, onChange, focusTrigger]
  );

  // Enter belongs to the dropdown: the create row covers free-form commits,
  // so the field's own Enter never fires here.
  const { onKeyDown, ...triggerAria } = getTriggerProps({ typeIn });

  return (
    <TagField
      tags={iconTags}
      onRemoveTag={onRemoveTag}
      readOnly={!typeIn}
      triggerRef={triggerRef}
      value={value}
      onChange={(next) => {
        onChange?.(next);
        if (!isOpen) setIsOpen(true);
        // No filter, no implicit pick: Enter on an empty input must not
        // commit the first row.
        setHighlightedIndex(next.trim() === "" ? -1 : 0);
        setIsKeyboardNav(false);
      }}
      placeholder={placeholder}
      variant={hasInvalidTag ? "error" : variant}
      disabled={disabled}
      icon={icon}
      onClear={onClear}
      minRows={minRows}
      maxRows={maxRows}
      focusOnMount={focusOnMount}
      rootRef={setAnchorRef}
      inputRef={inputRef}
      onInputKeyDown={onKeyDown}
      // A click opens either trigger; a second click closes a button
      // trigger, and a type-in also opens on typing. Focus alone never
      // opens the list, so tabbing through a form passes by.
      onInputClick={() => setIsOpen((prev) => (typeIn ? true : !prev))}
      inputAriaProps={{
        ...triggerAria,
        "aria-label": placeholder ?? "",
        "aria-invalid": hasInvalidTag,
      }}
    >
      <SelectChevron
        isOpen={isOpen}
        disabled={disabled}
        onToggle={() => {
          setIsOpen((prev) => !prev);
          focusTrigger();
        }}
      />

      <Dropdown.Data
        items={items}
        label={placeholder ?? ""}
        query={typeIn ? value : undefined}
        search={
          search ? { placeholder: strings.selectSearchPlaceholder } : undefined
        }
        values={selectedValues}
        closeOnSelect={false}
        onSelect={handleOptionSelect}
        create={
          showCreateOption
            ? { text: value.trim(), onCreate: handleCreate }
            : undefined
        }
        maxHeight={dropdownMaxHeight}
      />
    </TagField>
  );
}

export { MultiDropdown, type TagItem };
