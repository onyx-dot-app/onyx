"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useFormikContext } from "formik";
import { Button, Dropdown, type DropdownMenuItem } from "@opal/components";
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
  const t = useTranslations("agents");
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
  }

  function toItem(placeholder: UserPlaceholder): DropdownMenuItem {
    return {
      kind: "action",
      id: placeholder.key,
      icon: SvgBracketCurly,
      title: placeholder.label,
      description: userPlaceholderToken(placeholder.key),
      onSelect: () => insertToken(placeholder.key),
    };
  }

  return (
    <Dropdown open={open} onOpenChange={setOpen}>
      <Dropdown.Trigger asChild>
        <Button
          prominence="internal"
          size="xs"
          icon={SvgBracketCurly}
          tooltip={t("userVariables.insert.tooltip")}
          aria-label={t("userVariables.insert.tooltip")}
        />
      </Dropdown.Trigger>
      <Dropdown.Data
        label={t("userVariables.insert.tooltip")}
        items={[
          ...USER_DIRECTORY_PLACEHOLDERS.map(toItem),
          ...USER_IDENTITY_PLACEHOLDERS.map(toItem),
        ]}
      />
    </Dropdown>
  );
}
