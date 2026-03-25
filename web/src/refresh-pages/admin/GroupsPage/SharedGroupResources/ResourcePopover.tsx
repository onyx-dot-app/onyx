"use client";

import { useState } from "react";
import { SvgEmpty } from "@opal/icons";
import { Content } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import Popover from "@/refresh-components/Popover";
import Separator from "@/refresh-components/Separator";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import type { ResourcePopoverProps } from "@/refresh-pages/admin/GroupsPage/SharedGroupResources/interfaces";

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
              (section, idx) =>
                section.items.length > 0 && (
                  <div key={section.label ?? `section-${idx}`}>
                    {section.label && (
                      <Section
                        flexDirection="row"
                        gap={0.25}
                        padding={0}
                        height="auto"
                        alignItems="center"
                        justifyContent="start"
                        className="px-2 pt-2 pb-1"
                      >
                        <Text secondaryBody text03 className="shrink-0">
                          {section.label}
                        </Text>
                        <Separator noPadding className="flex-1" />
                      </Section>
                    )}
                    <Section
                      gap={0.25}
                      alignItems="stretch"
                      justifyContent="start"
                    >
                      {section.items.map((item) => (
                        <div
                          key={item.key}
                          className={cn(
                            "rounded-08 cursor-pointer",
                            item.disabled
                              ? "bg-background-tint-02"
                              : "hover:bg-background-tint-02 transition-colors"
                          )}
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
