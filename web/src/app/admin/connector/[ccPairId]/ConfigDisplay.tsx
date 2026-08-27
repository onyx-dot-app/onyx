"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ValidSources } from "@/lib/types";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { Button, Divider } from "@opal/components";
import { SvgChevronUp, SvgChevronDown, SvgEdit } from "@opal/icons";
import Truncated from "@/refresh-components/texts/Truncated";

function convertObjectToString(obj: any): string | any {
  if (typeof obj === "object" && obj !== null) {
    if (!Array.isArray(obj)) {
      return JSON.stringify(obj);
    } else {
      if (obj.length === 0) {
        return null;
      }
      return obj.map((item) => convertObjectToString(item)).join(", ");
    }
  }
  if (typeof obj === "boolean") {
    return obj.toString();
  }
  return obj;
}

export function buildConfigEntries(
  obj: any,
  sourceType: ValidSources
): { [key: string]: string } {
  if (sourceType === ValidSources.File) {
    return {};
  } else if (sourceType === ValidSources.GoogleSites) {
    return {
      base_url: obj.base_url,
    };
  }
  return obj;
}

interface ConfigItemProps {
  label: string;
  value: any;
  onEdit?: () => void;
}

function ConfigItem({ label, value, onEdit }: ConfigItemProps) {
  const t = useTranslations("admin.connector");
  const [isExpanded, setIsExpanded] = useState(false);
  const isExpandable = Array.isArray(value) && value.length > 5;

  const renderValue = () => {
    if (Array.isArray(value)) {
      const displayedItems = isExpanded ? value : value.slice(0, 5);
      return (
        <Section
          flexDirection="row"
          gap={1}
          justifyContent="end"
          alignItems="center"
          height="fit"
        >
          <Text secondaryBody text03 className="wrap-break-word">
            {displayedItems
              .map((item) => convertObjectToString(item))
              .join(", ")}
          </Text>
        </Section>
      );
    } else if (typeof value === "object" && value !== null) {
      return (
        <Section gap={1} alignItems="end" height="fit">
          {Object.entries(value).map(([key, val]) => (
            <Text key={key} secondaryBody text03 className="wrap-break-word">
              <Text mainContentEmphasis text03>
                {key}:
              </Text>{" "}
              {convertObjectToString(val)}
            </Text>
          ))}
        </Section>
      );
    } else if (typeof value === "boolean") {
      return (
        <Text secondaryBody text03 className="text-right">
          {value ? t("configItem.booleanTrue") : t("configItem.booleanFalse")}
        </Text>
      );
    }
    return (
      <Truncated secondaryBody text03 className="text-right">
        {convertObjectToString(value) || "-"}
      </Truncated>
    );
  };

  return (
    <Section
      flexDirection="row"
      justifyContent="between"
      alignItems="center"
      gap={4}
    >
      <Section alignItems="start">
        <Text mainUiBody text04>
          {label}
        </Text>
      </Section>
      <Section
        flexDirection="row"
        justifyContent="end"
        alignItems="center"
        gap={2}
      >
        {renderValue()}

        {isExpandable && (
          <Button
            prominence="tertiary"
            size="md"
            icon={isExpanded ? SvgChevronUp : SvgChevronDown}
            onClick={() => setIsExpanded(!isExpanded)}
          >
            {isExpanded
              ? t("configItem.showLess.label")
              : t("configItem.showAll.label", { count: value.length })}
          </Button>
        )}
        {onEdit && (
          <Button
            prominence="tertiary"
            icon={SvgEdit}
            onClick={onEdit}
            tooltip={t("configItem.edit.tooltip")}
          />
        )}
      </Section>
    </Section>
  );
}

export function AdvancedConfigDisplay({
  pruneFreq,
  refreshFreq,
  indexingStart,
  onRefreshEdit,
  onPruningEdit,
}: {
  pruneFreq: number | null;
  refreshFreq: number | null;
  indexingStart: Date | null;
  // Omit to hide the pencil for a caller who may not edit.
  onRefreshEdit?: () => void;
  onPruningEdit?: () => void;
}) {
  const t = useTranslations("admin.connector");
  const locale = useLocale();

  const formatRefreshFrequency = (seconds: number | null): string => {
    if (seconds === null) return "-";
    const totalMinutes = seconds / 60;

    // If it's 60 minutes or more and evenly divisible by 60, show in hours
    if (totalMinutes >= 60 && totalMinutes % 60 === 0) {
      return t("advancedConfig.duration.hours", {
        count: totalMinutes / 60,
      });
    }

    // Otherwise show in minutes
    return t("advancedConfig.duration.minutes", {
      count: Math.round(totalMinutes),
    });
  };
  const formatPruneFrequency = (seconds: number | null): string => {
    if (seconds === null) return "-";
    const totalHours = seconds / 3600;

    // If less than 1 hour, show in minutes
    if (totalHours < 1) {
      return t("advancedConfig.duration.minutes", {
        count: Math.round(seconds / 60),
      });
    }

    const hours = Math.round(totalHours);

    // If it's 24 hours or more and evenly divisible by 24, show in days
    if (hours >= 24 && hours % 24 === 0) {
      return t("advancedConfig.duration.days", { count: hours / 24 });
    }

    // Otherwise show in hours
    return t("advancedConfig.duration.hours", { count: hours });
  };

  const formatDate = (date: Date | null): string => {
    if (date === null) return "-";
    return date.toLocaleString(locale, {
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short",
    });
  };

  const items = [
    pruneFreq !== null && {
      label: t("advancedConfig.pruningFrequency.label"),
      value: formatPruneFrequency(pruneFreq),
      onEdit: onPruningEdit,
    },
    refreshFreq && {
      label: t("advancedConfig.refreshFrequency.label"),
      value: formatRefreshFrequency(refreshFreq),
      onEdit: onRefreshEdit,
    },
    indexingStart && {
      label: t("advancedConfig.indexingStart.label"),
      value: formatDate(indexingStart),
    },
  ].filter(Boolean) as ConfigItemProps[];

  return (
    <Section gap={0} height="fit">
      {items.map((item, index) => (
        <div key={item.label} className="w-full">
          <div className="py-4">
            <ConfigItem
              label={item.label}
              value={item.value}
              onEdit={item.onEdit}
            />
          </div>
          {index < items.length - 1 && (
            <Divider paddingParallel={0} paddingPerpendicular={0} />
          )}
        </div>
      ))}
    </Section>
  );
}

export function ConfigDisplay({
  configEntries,
  onEdit,
}: {
  configEntries: { [key: string]: string };
  onEdit?: (key: string) => void;
}) {
  const entries = Object.entries(configEntries);

  return (
    <Section gap={0} height="fit">
      {entries.map(([key, value], index) => (
        <div key={key} className="w-full">
          <div className="py-4">
            <ConfigItem
              label={key}
              value={value}
              onEdit={onEdit ? () => onEdit(key) : undefined}
            />
          </div>
          {index < entries.length - 1 && (
            <Divider paddingParallel={0} paddingPerpendicular={0} />
          )}
        </div>
      ))}
    </Section>
  );
}
