"use client";

import type { ReactNode } from "react";
import { Tag, Text, type TagProps } from "@opal/components";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { cn } from "@opal/utils";

interface PluginRowLayoutProps {
  icon: IconFunctionComponent;
  title: string | RichStr;
  description: string | RichStr;
  descriptionTag?: Pick<TagProps, "title" | "color" | "tooltip">;
  action: ReactNode;
  status?: ReactNode;
}

export default function PluginRowLayout({
  icon: Icon,
  title,
  description,
  descriptionTag,
  action,
  status,
}: PluginRowLayoutProps) {
  return (
    <div
      className={cn(
        "flex min-h-20 min-w-0 gap-4 px-3 py-4",
        status ? "items-start" : "items-center"
      )}
    >
      <div className="flex size-[42px] shrink-0 items-center justify-center rounded-12 border border-border-01 bg-background-neutral-00">
        <Icon size={24} className="text-text-03" />
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-[42px] min-w-0 flex-col justify-center">
          <div className="min-w-0 truncate">
            <Text font="main-content-body" color="text-05">
              {title}
            </Text>
          </div>
          <div className="flex min-w-0 items-center gap-2 leading-none">
            <div className="min-w-0 truncate">
              <Text font="secondary-body" color="text-03">
                {description}
              </Text>
            </div>
            {descriptionTag && (
              <div className="shrink-0">
                <Tag {...descriptionTag} />
              </div>
            )}
          </div>
        </div>
        {status && <div className="pt-1">{status}</div>}
      </div>
      <div className="flex h-[42px] shrink-0 items-center gap-2">{action}</div>
    </div>
  );
}
