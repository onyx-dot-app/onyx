"use client";

import React, { useState, useCallback } from "react";
import Modal from "@/refresh-components/Modal";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import KeyValueInput, {
  type KeyValue,
} from "@/refresh-components/inputs/InputKeyValue";
import { SvgSettings } from "@opal/icons";
import { updateToolForcedArgs } from "@/lib/tools/mcpService";

interface ForcedArgsModalProps {
  toolId: number;
  toolName: string;
  forcedArgs: Record<string, any> | null;
  onClose: () => void;
  onSaved: () => void;
}

function toKeyValueItems(args: Record<string, any> | null): KeyValue[] {
  if (!args || Object.keys(args).length === 0) return [];
  return Object.entries(args).map(([key, value]) => ({
    key,
    value: typeof value === "string" ? value : JSON.stringify(value),
  }));
}

function parseValue(value: string): any {
  // Preserve original JSON types: booleans, numbers, null, objects, arrays
  try {
    const parsed = JSON.parse(value);
    return parsed;
  } catch {
    // Not valid JSON — treat as plain string
    return value;
  }
}

function toForcedArgs(items: KeyValue[]): Record<string, any> | null {
  const filtered = items.filter((item) => item.key.trim() !== "");
  if (filtered.length === 0) return null;
  return Object.fromEntries(
    filtered.map((item) => [item.key, parseValue(item.value)])
  );
}

export default function ForcedArgsModal({
  toolId,
  toolName,
  forcedArgs,
  onClose,
  onSaved,
}: ForcedArgsModalProps) {
  const [items, setItems] = useState<KeyValue[]>(toKeyValueItems(forcedArgs));
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  const handleSave = useCallback(async () => {
    if (validationError) return;

    setIsSaving(true);
    setError(null);
    try {
      await updateToolForcedArgs(toolId, toForcedArgs(items));
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setIsSaving(false);
    }
  }, [toolId, items, validationError, onSaved, onClose]);

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="md">
        <Modal.Header
          icon={SvgSettings}
          title="Forced Arguments"
          description={toolName}
          onClose={onClose}
        />
        <Modal.Body>
          <div className="flex flex-col gap-3">
            <Text as="p" text03 secondaryBody>
              Forced arguments are always injected into this tool&apos;s calls,
              overriding any values the AI provides. Useful for ensuring specific
              values like theme IDs or organization IDs.
            </Text>

            <KeyValueInput
              keyTitle="Argument"
              valueTitle="Value"
              keyPlaceholder="e.g. theme_id"
              valuePlaceholder="e.g. abc-123"
              items={items}
              onChange={setItems}
              mode="line"
              layout="key-wide"
              onValidationError={setValidationError}
              addButtonLabel="Add Argument"
            />

            {error && (
              <Text as="p" className="text-status-error-05">
                {error}
              </Text>
            )}
          </div>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={isSaving || !!validationError}
          >
            {isSaving ? "Saving..." : "Save"}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
