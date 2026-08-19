"use client";

import { useState } from "react";
import { useFormikContext } from "formik";
import { Popover, PopoverMenu } from "@opal/components";
import LineItem from "@/refresh-components/buttons/LineItem";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgBracketCurly } from "@opal/icons";
import {
  USER_DIRECTORY_PLACEHOLDERS,
  USER_IDENTITY_PLACEHOLDERS,
  UserPlaceholder,
  userPlaceholderToken,
} from "@/lib/agents/userPlaceholders";

interface InsertUserVariableMenuProps {
  // Formik field name of the target textarea. Doubles as the textarea DOM id
  // (InputTextAreaField sets `id={name}`), which lets us insert at the caret.
  fieldName: string;
}

// A compact "insert variable" affordance for agent prompt textareas. Lists the
// available `{{user.<key>}}` placeholders and splices the chosen token at the
// current caret position of the associated textarea.
export default function InsertUserVariableMenu({
  fieldName,
}: InsertUserVariableMenuProps) {
  const [open, setOpen] = useState(false);
  const { setFieldValue, values } = useFormikContext<Record<string, unknown>>();

  function insertToken(key: string) {
    const token = userPlaceholderToken(key);
    const textarea = document.getElementById(
      fieldName
    ) as HTMLTextAreaElement | null;

    if (textarea) {
      const start = textarea.selectionStart ?? textarea.value.length;
      const end = textarea.selectionEnd ?? textarea.value.length;
      const next =
        textarea.value.slice(0, start) + token + textarea.value.slice(end);
      setFieldValue(fieldName, next);
      // Restore focus and place the caret right after the inserted token, once
      // the controlled value has been applied.
      requestAnimationFrame(() => {
        textarea.focus();
        const caret = start + token.length;
        textarea.setSelectionRange(caret, caret);
      });
    } else {
      const current = String(values[fieldName] ?? "");
      setFieldValue(fieldName, current + token);
    }

    setOpen(false);
  }

  function renderItem(placeholder: UserPlaceholder) {
    return (
      <LineItem
        key={placeholder.key}
        icon={SvgBracketCurly}
        description={userPlaceholderToken(placeholder.key)}
        onClick={() => insertToken(placeholder.key)}
      >
        {placeholder.label}
      </LineItem>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <div>
          <IconButton
            internal
            small
            icon={SvgBracketCurly}
            tooltip="Insert user variable"
          />
        </div>
      </Popover.Trigger>
      <Popover.Content>
        <PopoverMenu>
          {[
            ...USER_DIRECTORY_PLACEHOLDERS.map(renderItem),
            ...USER_IDENTITY_PLACEHOLDERS.map(renderItem),
          ]}
        </PopoverMenu>
      </Popover.Content>
    </Popover>
  );
}
