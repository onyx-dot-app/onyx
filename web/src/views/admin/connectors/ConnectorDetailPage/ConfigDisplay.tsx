"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, OverflowText, Text } from "@opal/components";
import { richNodes } from "@opal/utils";
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

/** One setting: its config key, the label to show for it, and its stored value. */
export interface ConfigRow {
  key: string;
  label: string | RichStr;
  value: ConfigValue;
  /** A boolean shown by the form's tab labels, e.g. "Confluence Cloud". */
  booleanLabels?: { true: string; false: string };
}

type ConfigItemProps = Omit<ConfigRow, "key">;

/** An http(s) URL split for display, or null for any other value. */
export function splitUrl(
  value: string
): { scheme: string; host: string; path: string } | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return {
      scheme: `${url.protocol}//`,
      host: url.host,
      path: `${url.pathname}${url.search}${url.hash}`,
    };
  } catch {
    return null;
  }
}

function ConfigItem({ label, value, booleanLabels }: ConfigItemProps) {
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
        <Text
          as="p"
          font="main-ui-body"
          color="text-04"
          textPosition="text-end"
        >
          {displayedItems.map((item) => convertObjectToString(item)).join(", ")}
        </Text>
      );
    }
    if (typeof value === "object" && value !== null) {
      return (
        <Section gap={1} alignItems="end" height="fit">
          {Object.entries(value).map(([key, val]) => (
            <Text key={key} font="main-ui-body" color="text-04">
              {`${key}: ${convertObjectToString(val) ?? ""}`}
            </Text>
          ))}
        </Section>
      );
    }
    if (typeof value === "boolean") {
      const labels = booleanLabels ?? {
        true: t("configItem.booleanTrue"),
        false: t("configItem.booleanFalse"),
      };
      return (
        <Text font="main-ui-body" color="text-04">
          {value ? labels.true : labels.false}
        </Text>
      );
    }
    // As the section summary shows a host: the host bold, the rest muted.
    const url = typeof value === "string" ? splitUrl(value) : null;
    if (url !== null) {
      return (
        <Text
          as="p"
          font="main-ui-body"
          color="text-03"
          wordWrap="wrap-anywhere"
        >
          {richNodes(
            <>
              {url.scheme}
              <Text font="main-ui-action" color="text-04">
                {url.host}
              </Text>
              {url.path}
            </>
          )}
        </Text>
      );
    }
    return (
      <OverflowText
        as="p"
        font="main-ui-body"
        color="text-04"
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
      alignItems="start"
      gap={2}
      height="fit"
    >
      <Section alignItems="start" height="fit" className="min-w-0 flex-1">
        <Text font="main-ui-action" color="text-03">
          {label}
        </Text>
      </Section>
      <Section
        flexDirection="row"
        justifyContent="end"
        alignItems="center"
        gap={1}
        width="fit"
        height="fit"
        className="min-w-0 max-w-60"
      >
        {renderValue()}
        {isExpandable && (
          <Button
            prominence="tertiary"
            size="xs"
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
  rows: ConfigRow[];
}

/** Settings as label and value rows. */
export function ConfigDisplay({ rows }: ConfigDisplayProps) {
  return (
    <Section gap={3} height="fit" alignItems="stretch">
      {rows.map((row) => (
        <ConfigItem
          key={row.key}
          label={row.label}
          value={row.value}
          booleanLabels={row.booleanLabels}
        />
      ))}
    </Section>
  );
}
