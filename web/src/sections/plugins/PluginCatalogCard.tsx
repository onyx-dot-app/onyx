"use client";

import { SelectCard } from "@opal/components";
import { SvgPlus } from "@opal/icons";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import PluginRowLayout from "@/sections/plugins/PluginRowLayout";

interface PluginCatalogCardProps {
  icon: IconFunctionComponent;
  title: string | RichStr;
  description: string | RichStr;
  label: string;
  onSelect: () => void;
}

export default function PluginCatalogCard({
  icon,
  title,
  description,
  label,
  onSelect,
}: PluginCatalogCardProps) {
  return (
    <SelectCard
      border="none"
      padding={0}
      role="button"
      tabIndex={0}
      aria-label={label}
      onClick={onSelect}
    >
      <PluginRowLayout
        icon={icon}
        title={title}
        description={description}
        action={
          <span className="flex size-8 items-center justify-center">
            <SvgPlus size={16} aria-hidden className="text-text-03" />
          </span>
        }
      />
    </SelectCard>
  );
}
