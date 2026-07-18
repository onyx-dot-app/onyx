import React from "react";
import {
  ArrayHelpers,
  ErrorMessage,
  Field,
  FieldArray,
  useFormikContext,
} from "formik";
import { FiX } from "react-icons/fi";
import { Button } from "@opal/components";
import { SvgPlusCircle } from "@opal/icons";
import { Label, SubLabel } from "@/components/Field";

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

const FIELD_CLASSES = `
  border
  border-border
  bg-background
  rounded
  w-full
  py-2
  px-3
  disabled:cursor-not-allowed
`;

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
    <div className="mb-4">
      <Label>{label}</Label>
      {description && <SubLabel>{description}</SubLabel>}

      <FieldArray
        name={name}
        render={(arrayHelpers: ArrayHelpers) => (
          <div>
            {pairs.length > 0 && (
              <div className="flex mt-2 text-sm text-text-500">
                <div className="w-full mr-2">{leftLabel}</div>
                <div className="w-full">{rightLabel}</div>
                <div className="w-10 shrink-0" />
              </div>
            )}
            {pairs.map((_, index) => (
              <div key={rowIdsRef.current[index]} className="mt-2">
                <div className="flex items-center">
                  <Field
                    name={`${name}.${index}.${leftKey}`}
                    className={`${FIELD_CLASSES} mr-2`}
                    autoComplete="off"
                    placeholder={leftPlaceholder}
                  />
                  <Field
                    name={`${name}.${index}.${rightKey}`}
                    className={FIELD_CLASSES}
                    autoComplete="off"
                    placeholder={rightPlaceholder}
                  />
                  <FiX
                    className="w-10 h-10 shrink-0 cursor-pointer hover:bg-background-neutral-02 rounded-sm p-2"
                    onClick={() => {
                      rowIdsRef.current.splice(index, 1);
                      arrayHelpers.remove(index);
                    }}
                  />
                </div>
                <ErrorMessage
                  name={`${name}.${index}`}
                  component="div"
                  className="text-action-danger-05 text-sm mt-1"
                />
              </div>
            ))}

            <div className="mt-2">
              <Button
                icon={SvgPlusCircle}
                prominence="secondary"
                onClick={() =>
                  arrayHelpers.push({ [leftKey]: "", [rightKey]: "" })
                }
                type="button"
              >
                Add New
              </Button>
            </div>
          </div>
        )}
      />
    </div>
  );
};

export default StringPairListInput;
