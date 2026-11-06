"use client";

import { useEffect, useMemo } from "react";
import { useField } from "formik";
import { InputMultiComboBoxField } from "@opal/form";
import type { SelectOption } from "@opal/components/inputs/dropdowns/types";
import TextListField from "@/refresh-components/form/TextListField";
import { useFindingOptions } from "@/lib/connectors/checks/hooks";
import type { StoredReportScope } from "@/lib/connectors/checks/findings";
import type { CheckFindingKey } from "@/lib/connectors/checks/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";

interface FindingListFieldProps {
  name: string;
  connector: ConfigurableSources;
  /** The discovery finding that lists the options. */
  findingKey: CheckFindingKey;
  /** The stored reports that supply the options before a run. */
  reportScope: StoredReportScope | null;
  /** Typed entries only, as in a regex mode: a plain list of the labels. */
  plain: boolean;
  placeholder: string;
  plainPlaceholder: string;
  disabled: boolean;
}

/** List field fed by a discovery listing: a pick stores the value and shows the label. Free text still commits. */
export default function FindingListField({
  name,
  connector,
  findingKey,
  reportScope,
  plain,
  placeholder,
  plainPlaceholder,
  disabled,
}: FindingListFieldProps) {
  const findingOptions = useFindingOptions(connector, findingKey, reportScope);
  const [field, , helpers] = useField<string[]>(name);
  const options = useMemo<SelectOption[]>(
    () =>
      findingOptions.map((option) => ({
        value: option.value,
        title: option.label,
        description: option.detail ?? undefined,
        // A search by the stored value finds the row too.
        keywords: [option.value],
      })),
    [findingOptions]
  );

  // A plain list takes names, so a picked id becomes its label.
  useEffect(() => {
    if (!plain) return;
    const labels = new Map(
      findingOptions.map((option) => [option.value, option.label])
    );
    const entries: string[] = field.value ?? [];
    if (!entries.some((entry) => labels.has(entry))) return;
    void helpers.setValue(entries.map((entry) => labels.get(entry) ?? entry));
  }, [plain, findingOptions, field.value, helpers]);

  if (plain) {
    return (
      <TextListField
        name={name}
        placeholder={plainPlaceholder}
        disabled={disabled}
      />
    );
  }
  return (
    <InputMultiComboBoxField
      name={name}
      mode="open"
      options={options}
      placeholder={placeholder}
      disabled={disabled}
    />
  );
}
