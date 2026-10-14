"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Divider, OverflowText, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgChevronDown, SvgChevronUp } from "@opal/icons";
import { ValidSources } from "@/lib/connectors/types/source";
import type { RichStr } from "@opal/types";
import type { ConfigEntries, ConfigValue } from "@/lib/connectors/types";

// Arrays past this length fold behind a "Show all" button.
const FOLDED_LIST_LENGTH = 5;

function convertObjectToString(value: ConfigValue): string | null {
  if (Array.isArray(value)) {
    if (value.length === 0) return null;
    return value.map((item) => convertObjectToString(item)).join(", ");
  }
  if (typeof value === "object" && value !== null) {
    return JSON.stringify(value);
  }
  if (value === null || value === undefined) return null;
  return String(value);
}

/** The rows to show: a file connector's files have their own manager, Google Sites shows only its URL. */
export function buildConfigEntries(
  config: ConfigEntries,
  sourceType: ValidSources
): ConfigEntries {
  if (sourceType === ValidSources.File) return {};
  if (sourceType === ValidSources.GoogleSites) {
    return { base_url: config.base_url };
  }
  return config;
}

interface ConfigItemProps {
  label: string | RichStr;
  value: ConfigValue;
}

function ConfigItem({ label, value }: ConfigItemProps) {
  const t = useTranslations("admin.connector");
  const [isExpanded, setIsExpanded] = useState(false);
  const isExpandable =
    Array.isArray(value) && value.length > FOLDED_LIST_LENGTH;

  function renderValue() {
    if (Array.isArray(value)) {
      const displayedItems = isExpanded
        ? value
        : value.slice(0, FOLDED_LIST_LENGTH);
      return (
        <Text font="secondary-body" color="text-03">
          {displayedItems.map((item) => convertObjectToString(item)).join(", ")}
        </Text>
      );
    }
    if (typeof value === "object" && value !== null) {
      return (
        <Section gap={1} alignItems="end" height="fit">
          {Object.entries(value).map(([key, val]) => (
            <Text key={key} font="secondary-body" color="text-03">
              {`${key}: ${convertObjectToString(val) ?? ""}`}
            </Text>
          ))}
        </Section>
      );
    }
    if (typeof value === "boolean") {
      return (
        <Text font="secondary-body" color="text-03">
          {value ? t("configItem.booleanTrue") : t("configItem.booleanFalse")}
        </Text>
      );
    }
    return (
      <OverflowText
        as="p"
        font="secondary-body"
        color="text-03"
        textPosition="text-end"
      >
        {convertObjectToString(value) || "-"}
      </OverflowText>
    );
  }

  return (
    <Section
      flexDirection="row"
      justifyContent="between"
      alignItems="center"
      gap={4}
      height="fit"
    >
      <Section alignItems="start" width="fit" height="fit">
        <Text font="main-ui-body" color="text-04">
          {label}
        </Text>
      </Section>
      <Section
        flexDirection="row"
        justifyContent="end"
        alignItems="center"
        gap={2}
        height="fit"
        className="min-w-0"
      >
        {renderValue()}
        {isExpandable && (
          <Button
            prominence="tertiary"
            icon={isExpanded ? SvgChevronUp : SvgChevronDown}
            onClick={() => setIsExpanded(!isExpanded)}
          >
            {isExpanded
              ? t("configItem.showLess.label")
              : t("configItem.showAll.label", { count: value.length })}
          </Button>
        )}
      </Section>
    </Section>
  );
}

export interface ConfigDisplayProps {
  configEntries: ConfigEntries;
}

/** The connector's settings as label and value rows. */
export function ConfigDisplay({ configEntries }: ConfigDisplayProps) {
  const entries = Object.entries(configEntries);

  return (
    <Section gap={0} height="fit" alignItems="stretch">
      {entries.map(([key, value], index) => (
        <Section key={key} gap={0} height="fit" alignItems="stretch">
          <Section padding={2} height="fit" alignItems="stretch">
            <ConfigItem label={key} value={value} />
          </Section>
          {index < entries.length - 1 && (
            <Divider paddingParallel={0} paddingPerpendicular={0} />
          )}
        </Section>
      ))}
    </Section>
  );
}
