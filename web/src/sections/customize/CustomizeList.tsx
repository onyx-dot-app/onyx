"use client";

import { Children, type MouseEventHandler, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  Badge,
  Button,
  Divider,
  Dropdown,
  Text,
  type DropdownMenuItem,
} from "@opal/components";
import { IllustrationContent, Section } from "@opal/layouts";
import { SvgFilter, SvgMoreHorizontal } from "@opal/icons";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import type { SkillStatusFilter } from "@/lib/customize/skills";

interface CustomizeGroupProps {
  title: string | RichStr;
  children: ReactNode;
}

export function CustomizeGroup({ title, children }: CustomizeGroupProps) {
  const rows = Children.toArray(children);
  if (rows.length === 0) return null;
  return (
    <Section
      gap={1}
      alignItems="stretch"
      height="auto"
      role="region"
      aria-label={typeof title === "string" ? title : title.raw}
    >
      <Section
        flexDirection="row"
        justifyContent="start"
        alignItems="center"
        height="auto"
        gap={0.5}
      >
        <Text font="main-ui-action" color="text-04">
          {title}
        </Text>
        <Badge title={String(rows.length)} />
      </Section>
      <Section gap={0} alignItems="stretch" height="auto">
        {rows.map((row, index) => (
          <Section key={index} gap={0} height="auto">
            {index > 0 && (
              <Divider paddingParallel={0} paddingPerpendicular={0} />
            )}
            {row}
          </Section>
        ))}
      </Section>
    </Section>
  );
}

/** Opens a row on a single click only. A row action such as Turn on can
 * leave under the pointer, so the second click of a double-click lands on
 * the row and must not open it. */
export function openOnSingleClick(
  open: () => void
): MouseEventHandler<HTMLElement> {
  return (event) => {
    if (event.detail <= 1) open();
  };
}

interface CustomizeRowActionsProps {
  /** Shown in place of the date while the item is off. */
  turnOn?: { label: string | RichStr; disabled: boolean; onClick: () => void };
  date?: string | null;
  menuLabel: string;
  menu: DropdownMenuItem[];
}

export function CustomizeRowActions({
  turnOn,
  date,
  menuLabel,
  menu,
}: CustomizeRowActionsProps) {
  return (
    <Section
      flexDirection="row"
      justifyContent="end"
      alignItems="center"
      width="auto"
      height="auto"
      gap={1}
      onClick={(event) => event.stopPropagation()}
    >
      {turnOn ? (
        <Button
          size="sm"
          prominence="secondary"
          disabled={turnOn.disabled}
          onClick={turnOn.onClick}
        >
          {turnOn.label}
        </Button>
      ) : (
        date && (
          <Text font="secondary-body" color="text-03" maxLines={1}>
            {date}
          </Text>
        )
      )}
      {menu.length > 0 ? (
        <Dropdown align="end">
          <Dropdown.Trigger asChild>
            <Button
              size="sm"
              prominence="tertiary"
              icon={SvgMoreHorizontal}
              aria-label={menuLabel}
              tooltip={menuLabel}
            />
          </Dropdown.Trigger>
          <Dropdown.Data label={menuLabel} items={menu} />
        </Dropdown>
      ) : (
        <Section width={2} height="auto" />
      )}
    </Section>
  );
}

interface StatusFilterProps {
  value: SkillStatusFilter;
  onChange: (value: SkillStatusFilter) => void;
  allLabel: string;
}

export function StatusFilter({ value, onChange, allLabel }: StatusFilterProps) {
  const t = useTranslations("customize.skills.filter");
  return (
    <Dropdown align="end" width={60}>
      <Dropdown.Trigger asChild>
        <Button
          prominence="tertiary"
          icon={SvgFilter}
          interaction={value === "all" ? "rest" : "hover"}
          aria-label={t("label")}
          tooltip={t("label")}
        />
      </Dropdown.Trigger>
      <Dropdown.Data
        label={t("label")}
        items={[
          { kind: "option", value: "all", title: allLabel },
          { kind: "option", value: "on", title: t("on") },
          { kind: "option", value: "off", title: t("off") },
        ]}
        value={value}
        onSelect={(option) => {
          const next = option.value;
          if (next === "all" || next === "on" || next === "off") onChange(next);
        }}
      />
    </Dropdown>
  );
}

interface CustomizeEmptyProps {
  illustration: IconFunctionComponent;
  title: string | RichStr;
  description: string | RichStr;
  action?: ReactNode;
}

export function CustomizeEmpty({
  illustration,
  title,
  description,
  action,
}: CustomizeEmptyProps) {
  return (
    <Section gap={3} height="auto" padding={6}>
      <IllustrationContent
        illustration={illustration}
        title={title}
        description={description}
      />
      {action}
    </Section>
  );
}
