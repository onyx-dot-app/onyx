"use client";

import { useState } from "react";
import { SvgEmpty } from "@opal/icons";
import { Content } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import Popover from "@/refresh-components/Popover";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Text from "@/refresh-components/texts/Text";

interface PopoverItem {
  key: string;
  render: (disabled: boolean) => React.ReactNode;
  onSelect: () => void;
  /** When true, the item is already selected — shown dimmed with bg-tint-02. */
  disabled?: boolean;
}

interface PopoverSection {
  label?: string;
  items: PopoverItem[];
}

interface ResourcePopoverProps {
  placeholder: string;
  searchValue: string;
  onSearchChange: (value: string) => void;
  sections: PopoverSection[];
}

function SectionDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-1 px-2 pt-2 pb-1">
      <Text secondaryBody text03 className="shrink-0">
        {label}
      </Text>
      <div className="flex-1 h-px bg-border-01" />
    </div>
  );
}

function ResourcePopover({
  placeholder,
  searchValue,
  onSearchChange,
  sections,
}: ResourcePopoverProps) {
  const [open, setOpen] = useState(false);

  const totalItems = sections.reduce((sum, s) => sum + s.items.length, 0);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        onClick={(e) => {
          e.preventDefault();
        }}
      >
        <InputTypeIn
          placeholder={placeholder}
          value={searchValue}
          onChange={(e) => {
            onSearchChange(e.target.value);
            if (!open) setOpen(true);
          }}
          onFocus={() => setOpen(true)}
        />
      </Popover.Trigger>
      <Popover.Content
        width="trigger"
        align="start"
        sideOffset={4}
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <div className="flex flex-col gap-1 max-h-64 overflow-y-auto">
          {totalItems === 0 ? (
            <div className="px-3 py-3">
              <Content
                icon={SvgEmpty}
                title="No results found"
                sizePreset="secondary"
                variant="section"
              />
            </div>
          ) : (
            sections.map(
              (section) =>
                section.items.length > 0 && (
                  <div key={section.label ?? "default"}>
                    {section.label && <SectionDivider label={section.label} />}
                    <Section
                      gap={0.25}
                      alignItems="stretch"
                      justifyContent="start"
                    >
                      {section.items.map((item) => (
                        <div
                          key={item.key}
                          className={
                            item.disabled
                              ? "rounded-08 bg-background-tint-02 cursor-pointer"
                              : "rounded-08 cursor-pointer hover:bg-background-tint-02 transition-colors"
                          }
                          onClick={() => {
                            item.onSelect();
                          }}
                        >
                          {item.render(!!item.disabled)}
                        </div>
                      ))}
                    </Section>
                  </div>
                )
            )
          )}
        </div>
      </Popover.Content>
    </Popover>
  );
}

export default ResourcePopover;
export type { PopoverSection };
