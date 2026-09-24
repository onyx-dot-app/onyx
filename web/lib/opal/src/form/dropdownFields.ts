"use client";

import { useCallback, useMemo, useState } from "react";
import { useField } from "formik";
import {
  flattenSections,
  normalizeSections,
} from "@opal/components/inputs/dropdowns/shared";
import type {
  SelectOption,
  SelectSection,
} from "@opal/components/inputs/dropdowns/types";
import type { TagItem } from "@opal/components/inputs/texts/input-type-in-tag/TagField";

/**
 * Binds a single-arity dropdown to a Formik `string` field: a pick writes
 * the option value and marks the field touched; a touched field with an
 * error shows the error state.
 */
export function useSingleDropdownField(
  name: string,
  onValueChange?: (value: string) => void
) {
  const [field, meta, helpers] = useField<string>(name);
  const handleValueChange = useCallback(
    (value: string) => {
      void helpers.setValue(value);
      void helpers.setTouched(true);
      onValueChange?.(value);
    },
    [helpers, onValueChange]
  );
  return {
    value: field.value ?? "",
    onValueChange: handleValueChange,
    isError: meta.touched && meta.error !== undefined,
  };
}

/**
 * Binds a multi-arity dropdown to a Formik `string[]` field of option
 * values. A pick appends, unpicking or removing a chip drops, and both mark
 * the field touched. Chips take their labels from `options`; a stored value
 * outside the set shows as an error chip unless `mode="open"` legitimises
 * free-form values. The filter text (type-in only) is local state.
 */
export function useMultiDropdownField(
  name: string,
  options: SelectOption[] | SelectSection[],
  openSet: boolean
) {
  const [field, , helpers] = useField<string[]>(name);
  const selected = useMemo(() => field.value ?? [], [field.value]);
  const [filter, setFilter] = useState("");

  const flatOptions = useMemo(
    () => flattenSections(normalizeSections(options)),
    [options]
  );
  const tags = useMemo<TagItem[]>(
    () =>
      selected.map((value) => {
        const option = flatOptions.find(
          (candidate) => candidate.value === value
        );
        return {
          id: value,
          label: option?.label ?? value,
          error: option === undefined && !openSet,
        };
      }),
    [selected, flatOptions, openSet]
  );

  const commit = useCallback(
    (next: string[]) => {
      void helpers.setValue(next);
      void helpers.setTouched(true);
    },
    [helpers]
  );
  const add = useCallback(
    (value: string) => {
      if (!selected.includes(value)) commit([...selected, value]);
    },
    [selected, commit]
  );
  const remove = useCallback(
    (id: string) => commit(selected.filter((value) => value !== id)),
    [selected, commit]
  );
  const onSelectOption = useCallback(
    (option: SelectOption) => add(option.value),
    [add]
  );

  return { tags, filter, setFilter, add, remove, onSelectOption };
}
