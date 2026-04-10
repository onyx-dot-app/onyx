"use client";

import { useState } from "react";
import { Text } from "@opal/components";
import { Button } from "@opal/components/buttons/button/components";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { SvgPlus, SvgTrash } from "@opal/icons";

interface FieldMappingTableProps {
  title: string;
  description?: string;
  mapping: Record<string, string>;
  onUpdate: (mapping: Record<string, string>) => void;
  keyLabel?: string;
  valueLabel?: string;
}

function FieldMappingTable({
  title,
  description,
  mapping,
  onUpdate,
  keyLabel = "Key",
  valueLabel = "Value",
}: FieldMappingTableProps) {
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");

  function handleAdd() {
    if (!newKey.trim()) return;
    onUpdate({ ...mapping, [newKey.trim()]: newValue.trim() });
    setNewKey("");
    setNewValue("");
  }

  function handleRemove(key: string) {
    const updated = { ...mapping };
    delete updated[key];
    onUpdate(updated);
  }

  function handleValueChange(key: string, value: string) {
    onUpdate({ ...mapping, [key]: value });
  }

  const entries = Object.entries(mapping);

  return (
    <div className="flex flex-col gap-3">
      <div>
        <Text font="main-ui-action" color="text-01">
          {title}
        </Text>
        {description && (
          <Text font="secondary-body" color="text-03" as="p">
            {description}
          </Text>
        )}
      </div>

      {entries.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex gap-3 px-1">
            <span className="flex-1">
              <Text font="secondary-action" color="text-03">
                {keyLabel}
              </Text>
            </span>
            <span className="flex-1">
              <Text font="secondary-action" color="text-03">
                {valueLabel}
              </Text>
            </span>
            <div className="w-8" />
          </div>
          {entries.map(([key, value]) => (
            <div key={key} className="flex items-center gap-3">
              <div className="flex-1">
                <InputTypeIn
                  value={key}
                  variant="readOnly"
                  showClearButton={false}
                />
              </div>
              <div className="flex-1">
                <InputTypeIn
                  value={value}
                  onChange={(e) => handleValueChange(key, e.target.value)}
                  showClearButton={false}
                />
              </div>
              <Button
                icon={SvgTrash}
                prominence="tertiary"
                variant="danger"
                size="sm"
                onClick={() => handleRemove(key)}
                tooltip="Remove"
              />
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3">
        <div className="flex-1">
          <InputTypeIn
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            placeholder={`Add ${keyLabel.toLowerCase()}`}
            showClearButton={false}
          />
        </div>
        <div className="flex-1">
          <InputTypeIn
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            placeholder={`Add ${valueLabel.toLowerCase()}`}
            showClearButton={false}
          />
        </div>
        <Button
          icon={SvgPlus}
          prominence="tertiary"
          size="sm"
          onClick={handleAdd}
          disabled={!newKey.trim()}
          tooltip="Add entry"
        />
      </div>
    </div>
  );
}

export default FieldMappingTable;
