"use client";

import { useTranslations } from "next-intl";
import { InputTypeIn } from "@opal/components";
import { InputVertical } from "@opal/layouts";

const NAME_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const NAME_MAX_LENGTH = 64;

/** Whether `name` is a valid skill or plugin name that is not in `takenNames`. */
export function canUseName(name: string, takenNames: string[]): boolean {
  return (
    name.length <= NAME_MAX_LENGTH &&
    NAME_PATTERN.test(name) &&
    !takenNames.includes(name)
  );
}

interface TakenNameFieldProps {
  value: string;
  takenNames: string[];
  disabled?: boolean;
  onChange: (value: string) => void;
}

/** Asks for another name after a save refused a taken name. */
export default function TakenNameField({
  value,
  takenNames,
  disabled = false,
  onChange,
}: TakenNameFieldProps) {
  const t = useTranslations("skills.takenName");
  const error = takenNames.includes(value)
    ? t("taken", { name: value })
    : value.length > NAME_MAX_LENGTH || !NAME_PATTERN.test(value)
      ? t("invalid", { max: NAME_MAX_LENGTH })
      : undefined;
  return (
    <InputVertical
      withLabel
      title={t("title")}
      description={t("description")}
      error={error}
      disabled={disabled}
    >
      <InputTypeIn
        aria-label={t("title")}
        value={value}
        variant={disabled ? "disabled" : error ? "error" : "primary"}
        onChange={(event) => onChange(event.target.value)}
      />
    </InputVertical>
  );
}
