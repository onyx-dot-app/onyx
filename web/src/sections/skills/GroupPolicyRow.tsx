"use client";

import { useTranslations } from "next-intl";
import { Button, InputSingleSelect, type SelectOption } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgMinusCircle } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import {
  INHERIT,
  isPolicyChoice,
  type PolicyChoice,
} from "@/lib/skills/installationPolicy";

interface GroupPolicyRowProps {
  /** The group, or the plugin on the group page. */
  name: string;
  icon: IconFunctionComponent;
  description?: string;
  value: PolicyChoice;
  options: SelectOption[];
  disabled?: boolean;
  onChange: (choice: PolicyChoice) => void;
  /** Shows a remove button. Only a row that holds just a setting has one. */
  onRemove?: () => void;
}

/** One group install setting: a name, its setting, and a remove button. */
export default function GroupPolicyRow({
  name,
  icon,
  description,
  value,
  options,
  disabled = false,
  onChange,
  onRemove,
}: GroupPolicyRowProps) {
  const t = useTranslations("skills.modals.share.groupAccess");
  return (
    <Section
      role="group"
      aria-label={name}
      flexDirection="row"
      justifyContent="between"
      wrap
      gap={2}
      height="auto"
      padding={1}
    >
      <Section
        width="auto"
        height="auto"
        alignItems="start"
        className="min-w-0 grow basis-40"
      >
        <Content
          icon={icon}
          font="main-ui-body"
          title={name}
          description={description}
        />
      </Section>
      <Section
        flexDirection="row"
        width="auto"
        height="auto"
        gap={1}
        className="min-w-0 grow basis-56"
      >
        <Section width="full" height="auto" alignItems="stretch">
          <InputSingleSelect
            placeholder={t("select", { name })}
            value={value}
            defaultOption={INHERIT}
            options={options}
            disabled={disabled}
            onValueChange={(next) => {
              if (isPolicyChoice(next)) onChange(next);
            }}
          />
        </Section>
        {onRemove && (
          <Button
            icon={SvgMinusCircle}
            prominence="tertiary"
            tooltip={t("remove", { name })}
            aria-label={t("remove", { name })}
            disabled={disabled}
            onClick={onRemove}
          />
        )}
      </Section>
    </Section>
  );
}
