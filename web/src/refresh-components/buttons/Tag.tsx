"use client";

import React from "react";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { SVGProps } from "react";

const getVariantClasses = (active?: boolean) => [
  active ? "bg-background-tint-00" : "bg-background-tint-01",
  "hover:bg-background-tint-02",
];

interface TagProps {
  // Tag states:
  active?: boolean;

  // Tag content:
  label: string;
  className?: string;
  children: React.FunctionComponent<SVGProps<SVGSVGElement>>[];
  onClick?: React.MouseEventHandler;
}

export default function Tag({
  active,

  label,
  className,
  children,
  onClick,
}: TagProps) {
  // Show max 3 icons
  const visibleIcons = children.slice(0, 3);

  return (
    <button
      type="button"
      className={cn(
        "p-spacing-interline-mini rounded-08 group w-fit flex items-center gap-spacing-inline transition-all duration-200 ease-in-out",
        getVariantClasses(active),
        className
      )}
      onClick={onClick}
    >
      {/* Icons container */}
      <div className="flex items-center -space-x-spacing-inline">
        {visibleIcons.map((Icon, index) => (
          <div
            key={index}
            className="relative bg-background-tint-00 border border-background-tint-01 p-spacing-inline-mini rounded-04"
            style={{ zIndex: visibleIcons.length - index }}
          >
            <Icon className="w-[0.6rem] h-[0.6rem] stroke-text-04" />
          </div>
        ))}
      </div>

      {/* Count display - only shows on hover/active */}
      <div
        className={cn(
          "transition-all duration-200 ease-in-out overflow-hidden",
          "group-hover:max-w-8 group-hover:opacity-100",
          active ? "max-w-[10rem] opacity-100" : "max-w-0 opacity-0"
        )}
      >
        <Text>{children.length}</Text>
      </div>

      <Text>{label}</Text>
    </button>
  );
}
