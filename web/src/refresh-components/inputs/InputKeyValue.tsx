import React from "react";
import { cn } from "@/lib/utils";
import InputTypeIn from "./InputTypeIn";
import SvgMinusCircle from "@/icons/minus-circle";
import IconButton from "../buttons/IconButton";
import Button from "../buttons/Button";
import SvgPlusCircle from "@/icons/plus-circle";
import Text from "../texts/Text";

type KeyValue = { key: string; value: string };

interface KeyValueInputItemProps {
  item: KeyValue;
  onChange: (next: KeyValue) => void;
  disabled?: boolean;
  onRemove: () => void;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
}
const KeyValueInputItem = ({
  item,
  onChange,
  disabled,
  onRemove,
  keyPlaceholder,
  valuePlaceholder,
}: KeyValueInputItemProps) => {
  return (
    <div className="flex gap-1 items-center w-full">
      <div className="flex gap-2 flex-1">
        <InputTypeIn
          className="flex-1"
          placeholder={keyPlaceholder || "Key"}
          value={item.key}
          onChange={(e) => onChange({ ...item, key: e.target.value })}
          aria-label={keyPlaceholder || "Key"}
          disabled={disabled}
        />
        <InputTypeIn
          className="flex-1"
          placeholder={valuePlaceholder || "Value"}
          value={item.value}
          onChange={(e) => onChange({ ...item, value: e.target.value })}
          aria-label={valuePlaceholder || "Value"}
          disabled={disabled}
        />
      </div>
      <IconButton internal icon={SvgMinusCircle} onClick={onRemove} />
    </div>
  );
};

interface KeyValueInputProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "onChange"> {
  keyTitle: string;
  valueTitle: string;
  items: KeyValue[];
  onChange: (nextItems: KeyValue[]) => void;
  onAdd?: () => void;
  onRemove?: (index: number) => void;
  disabled?: boolean;
}

const KeyValueInput = ({
  keyTitle,
  valueTitle,
  items,
  onChange,
  onAdd,
  onRemove,
  disabled,
  className,
  ...rest
}: KeyValueInputProps) => {
  function handleAdd() {
    if (onAdd) return onAdd();
    onChange([...(items || []), { key: "", value: "" }]);
  }

  function handleRemove(index: number) {
    if (onRemove) return onRemove(index);
    const next = (items || []).filter((_, i) => i !== index);
    onChange(next);
  }

  function handleItemChange(index: number, nextItem: KeyValue) {
    const next = [...(items || [])];
    next[index] = nextItem;
    onChange(next);
  }

  return (
    <div className={cn("w-full flex flex-col gap-y-2", className)} {...rest}>
      <div className="flex gap-1 items-center w-full">
        <div className="flex gap-2 flex-1">
          <Text text04 mainUiAction className="flex-1">
            {keyTitle}
          </Text>
          <Text text04 mainUiAction className="flex-1">
            {valueTitle}
          </Text>
        </div>
        <div className="w-[1.5rem]" aria-hidden />
      </div>

      {items &&
        items.map((item, index) => (
          <KeyValueInputItem
            key={index}
            item={item}
            onChange={(next) => handleItemChange(index, next)}
            disabled={disabled}
            onRemove={() => handleRemove(index)}
            keyPlaceholder={keyTitle}
            valuePlaceholder={valueTitle}
          />
        ))}

      <div>
        <Button
          onClick={handleAdd}
          secondary
          disabled={disabled}
          leftIcon={SvgPlusCircle}
        >
          Add Item
        </Button>
      </div>
    </div>
  );
};

export default KeyValueInput;
