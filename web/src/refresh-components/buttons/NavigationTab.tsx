"use client";

import React, {
  useState,
  useEffect,
  Dispatch,
  SetStateAction,
  useRef,
} from "react";
import Link from "next/link";
import Text from "@/refresh-components/Text";
import { SvgProps } from "@/icons";
import SvgMoreHorizontal from "@/icons/more-horizontal";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
import Truncated from "@/refresh-components/Truncated";
import { useClickOutside } from "@/hooks/useClickOutside";
import { useKeyPress } from "@/hooks/useKeyPress";
import { useBoundingBox } from "@/hooks/useBoundingBox";

const textClasses = (active: boolean | undefined) =>
  ({
    main: [
      active ? "text-text-04" : "text-text-03",
      "group-hover/NavigationTab:text-text-04",
    ],
    danger: ["text-action-danger-05"],
    highlight: [
      active ? "text-text-05" : "text-text-04",
      "group-hover/NavigationTab:text-text-05",
    ],
    lowlight: [
      active ? "text-text-03" : "text-text-02",
      "group-hover/NavigationTab:text-text-03",
    ],
  }) as const;

const iconClasses = (active: boolean | undefined) =>
  ({
    main: [
      active ? "stroke-text-04" : "stroke-text-03",
      "group-hover/NavigationTab:stroke-text-04",
    ],
    danger: ["stroke-action-danger-05"],
    highlight: [
      active ? "stroke-text-04" : "stroke-text-03",
      "group-hover/NavigationTab:stroke-text-04",
    ],
    lowlight: [
      active ? "stroke-text-03" : "stroke-text-02",
      "group-hover/NavigationTab:stroke-text-03",
    ],
  }) as const;

export interface NavigationTabProps {
  // Button states:
  folded?: boolean;
  active?: boolean;

  // Button variants:
  danger?: boolean;
  highlight?: boolean;
  lowlight?: boolean;

  // Button properties:
  onClick?: React.MouseEventHandler<HTMLDivElement>;
  href?: string;
  tooltip?: boolean;
  popover?: React.ReactNode;
  onPopoverChange?: (open: boolean) => void;
  className?: string;
  icon: React.FunctionComponent<SvgProps>;
  renaming?: boolean;
  setRenaming?: Dispatch<SetStateAction<boolean>>;
  submitRename?: (renamingValue: string) => void;
  children?: string;
}

export default function NavigationTab({
  folded,
  active,

  danger,
  highlight,
  lowlight,

  onClick,
  href,
  tooltip,
  popover,
  onPopoverChange,
  className,
  icon: Icon,
  renaming,
  setRenaming,
  submitRename,
  children,
}: NavigationTabProps) {
  const { ref, inside } = useBoundingBox();
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [renamingValue, setRenamingValue] = useState<string>(children ?? "");
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!inputRef.current) return;
    setPopoverOpen(false);
    if (renaming) {
      setRenamingValue(children ?? "");
      inputRef.current.focus();
      inputRef.current.select();
    } else {
      setRenamingValue("");
    }
  }, [renaming, inputRef]);
  useEffect(() => {
    if (!onPopoverChange) return;
    // We add a 100ms timeout to ensure that the callback runs only when the fade-out animation has finished.
    setTimeout(() => onPopoverChange(popoverOpen), 100);
  }, [popoverOpen]);
  useClickOutside(inputRef, () => setRenaming?.(false), renaming);
  useKeyPress(() => setRenaming?.(false), "Escape", renaming);
  useKeyPress(
    () => {
      setRenaming?.(false);
      if (renamingValue) submitRename?.(renamingValue);
    },
    "Enter",
    renaming
  );

  const variant = danger
    ? "danger"
    : highlight
      ? "highlight"
      : lowlight
        ? "lowlight"
        : "main";

  const innerContent = (
    <div
      className={cn(
        "flex flex-row justify-center items-center p-spacing-inline gap-spacing-inline rounded-08 cursor-pointer hover:bg-background-tint-03 group/NavigationTab w-full select-none",
        active ? "bg-background-tint-00" : "bg-transparent",
        renaming && "border-[0.125rem] border-text-04",
        className
      )}
      onClick={href ? undefined : onClick}
      ref={ref}
    >
      <div
        className={cn(
          "flex-1 h-[1.5rem] flex flex-row items-center px-spacing-inline py-spacing-inline-mini gap-spacing-interline",
          folded ? "justify-center" : "justify-start"
        )}
      >
        <div className="w-[1rem] h-[1rem]">
          <Icon
            className={cn("h-[1rem] w-[1rem]", iconClasses(active)[variant])}
          />
        </div>
        {!folded &&
          (renaming && typeof children === "string" ? (
            <div className="flex flex-col justify-center items-start">
              <input
                ref={inputRef}
                value={renamingValue}
                onChange={(event) => setRenamingValue(event.target.value)}
                className="bg-transparent outline-none resize-none overflow-x-hidden overflow-y-hidden whitespace-nowrap no-scrollbar font-main-content-body w-full"
                autoFocus
              />
            </div>
          ) : typeof children === "string" ? (
            <Truncated
              side="right"
              // We offset the "truncation popover" iff the popover "kebab menu" exists.
              // This is because the popover would hover OVER the kebab menu, creating a weird UI.
              // However, if no popover is specified, we don't need to offset anything.
              offset={!!popover ? 40 : 0}
              className={cn("text-left", textClasses(active)[variant])}
            >
              {children}
            </Truncated>
          ) : (
            children
          ))}
      </div>
      {!folded && popover && (active || inside || popoverOpen) && (
        <Popover onOpenChange={setPopoverOpen}>
          <PopoverTrigger asChild onClick={(event) => event.stopPropagation()}>
            <div>
              <IconButton
                icon={SvgMoreHorizontal}
                internal
                active={popoverOpen}
              />
            </div>
          </PopoverTrigger>
          <PopoverContent
            align="end"
            side="right"
            avoidCollisions
            sideOffset={8}
          >
            {popover}
          </PopoverContent>
        </Popover>
      )}
    </div>
  );

  const content =
    folded && tooltip && typeof children === "string" ? (
      <Tooltip>
        <TooltipTrigger asChild>{innerContent}</TooltipTrigger>
        <TooltipContent align="center" side="right">
          <Text inverted>{children}</Text>
        </TooltipContent>
      </Tooltip>
    ) : (
      innerContent
    );

  if (href)
    return (
      <Link href={href} className="w-full h-fit">
        {content}
      </Link>
    );

  return content;
}
