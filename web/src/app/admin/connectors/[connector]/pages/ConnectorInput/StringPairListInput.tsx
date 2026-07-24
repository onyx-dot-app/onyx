import React from "react";
import {
  ArrayHelpers,
  ErrorMessage,
  FieldArray,
  useFormikContext,
} from "formik";
import { Button, Spacer, Text } from "@opal/components";
import { InputErrorText, InputVertical, Section } from "@opal/layouts";
import { SvgMinusCircle, SvgPlusCircle } from "@opal/icons";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";

interface StringPairListInputProps {
  name: string;
  label: string;
  description?: string;
  leftKey: string;
  rightKey: string;
  leftLabel: string;
  rightLabel: string;
  leftPlaceholder?: string;
  rightPlaceholder?: string;
}

// Matches the min-width of a `size="sm"` Button so the header column labels stay
// aligned with the input columns above each row's remove button.
const REMOVE_BUTTON_WIDTH_REM = 1.5;

/** A list of labeled string pairs rendered as two side-by-side inputs per row,
 * each serialized to an object keyed by leftKey/rightKey (e.g. URL rewrite
 * rules: { source: prefix, target: replacement }). */
const StringPairListInput: React.FC<StringPairListInputProps> = ({
  name,
  label,
  description,
  leftKey,
  rightKey,
  leftLabel,
  rightLabel,
  leftPlaceholder,
  rightPlaceholder,
}) => {
  const { values } = useFormikContext<Record<string, any>>();
  const pairs: Record<string, string>[] = values[name] || [];

  // Stable per-row keys so removing a middle row doesn't shift native input
  // state (focus/autofill) onto the row that takes its index. Index keys would;
  // content-derived keys would remount the row on every keystroke. New rows are
  // seeded here; the remove handler splices so each id stays with its row.
  const rowIdsRef = React.useRef<number[]>([]);
  const nextRowIdRef = React.useRef(0);
  while (rowIdsRef.current.length < pairs.length) {
    rowIdsRef.current.push(nextRowIdRef.current++);
  }
  if (rowIdsRef.current.length > pairs.length) {
    rowIdsRef.current.length = pairs.length;
  }

  return (
    <InputVertical title={label} description={description}>
      <FieldArray
        name={name}
        render={(arrayHelpers: ArrayHelpers) => (
          <Section gap={0.5} alignItems="start" width="full">
            {pairs.length > 0 && (
              <Section
                flexDirection="row"
                justifyContent="start"
                alignItems="center"
                gap={0.25}
                width="full"
              >
                <Section width="full" alignItems="start" gap={0}>
                  <Text font="secondary-body" color="text-03">
                    {leftLabel}
                  </Text>
                </Section>
                <Section width="full" alignItems="start" gap={0}>
                  <Text font="secondary-body" color="text-03">
                    {rightLabel}
                  </Text>
                </Section>
                <Spacer
                  orientation="horizontal"
                  rem={REMOVE_BUTTON_WIDTH_REM}
                />
              </Section>
            )}

            {pairs.map((_, index) => (
              <Section
                key={rowIdsRef.current[index]}
                gap={0.25}
                alignItems="start"
                width="full"
              >
                <Section
                  flexDirection="row"
                  justifyContent="start"
                  alignItems="center"
                  gap={0.25}
                  width="full"
                >
                  <InputTypeInField
                    name={`${name}.${index}.${leftKey}`}
                    placeholder={leftPlaceholder}
                    autoComplete="off"
                  />
                  <InputTypeInField
                    name={`${name}.${index}.${rightKey}`}
                    placeholder={rightPlaceholder}
                    autoComplete="off"
                  />
                  <Button
                    icon={SvgMinusCircle}
                    prominence="tertiary"
                    size="sm"
                    type="button"
                    tooltip="Remove"
                    onClick={() => {
                      rowIdsRef.current.splice(index, 1);
                      arrayHelpers.remove(index);
                    }}
                  />
                </Section>
                <ErrorMessage
                  name={`${name}.${index}`}
                  render={(msg) => (
                    <InputErrorText type="error">{msg}</InputErrorText>
                  )}
                />
              </Section>
            ))}

            <Button
              icon={SvgPlusCircle}
              prominence="secondary"
              type="button"
              onClick={() =>
                arrayHelpers.push({ [leftKey]: "", [rightKey]: "" })
              }
            >
              Add New
            </Button>
          </Section>
        )}
      />
    </InputVertical>
  );
};

export default StringPairListInput;
