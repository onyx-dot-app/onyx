"use client";

import { useId, useState, type ReactNode } from "react";
import { Button, Code, Fold } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import { SvgChevronDown } from "@opal/icons";
import { useOpalStrings } from "@opal/strings";
import { cn } from "@opal/utils";
import type { IconProps } from "@opal/types";
import type { ToolSnapshot } from "@/lib/tools/types";

export default function MCPToolRow({
  tool,
  control,
}: {
  tool: ToolSnapshot;
  control?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const strings = useOpalStrings();
  const name = tool.display_name || tool.name;
  function DisclosureIcon({ className, ...props }: IconProps) {
    return (
      <SvgChevronDown
        {...props}
        className={cn(
          className,
          "transition-transform motion-reduce:transition-none",
          open && "rotate-180"
        )}
      />
    );
  }

  return (
    <li className="min-w-0 px-4 py-3">
      <div role="presentation" onClick={() => setOpen((value) => !value)}>
        <ContentAction
          title={name}
          sizePreset="main-ui"
          variant="section"
          padding={0}
          center
          rightChildren={
            <div className="flex items-center gap-3">
              {control && (
                <div
                  role="presentation"
                  onClick={(event) => event.stopPropagation()}
                >
                  <div role="group" aria-label={name}>
                    {control}
                  </div>
                </div>
              )}
              <Button
                size="sm"
                prominence="tertiary"
                icon={DisclosureIcon}
                aria-label={
                  open
                    ? strings.collapsibleFoldSection(name)
                    : strings.collapsibleExpandSection(name)
                }
                aria-expanded={open}
                aria-controls={bodyId}
              />
            </div>
          }
        />
      </div>
      <Fold open={open} id={bodyId}>
        <div className="pt-3">
          <div
            className="max-h-56 overflow-y-auto"
            role="region"
            aria-label={name}
            // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Focus lets keyboard users scroll the description.
            tabIndex={0}
          >
            <Code>{tool.description}</Code>
          </div>
        </div>
      </Fold>
    </li>
  );
}
