"use client";

import React, { Dispatch, SetStateAction } from "react";
import { IconProps } from "@/components/icons/icons";
import Text from "@/components-2/Text";
import Truncated from "@/components-2/Truncated";
import SvgMoreHorizontal from "@/icons/more-horizontal";
import Link from "next/link";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { MenuButton } from "@/components-2/buttons/MenuButton";

export interface SidebarButtonProps {
  className?: string;
  icon?: React.FunctionComponent<IconProps>;
  active?: boolean;
  kebabMenu?: React.ReactNode;
  kebabMenuOpen?: boolean;
  setKebabMenuOpen?: Dispatch<SetStateAction<boolean>>;
  disableKebabHover?: boolean;
  grey?: boolean;
  hideTitle?: boolean;
  href?: string;
  onClick?: () => void;
  children?: React.ReactNode;
}

export function SidebarButton({
  className,
  icon: Icon,
  active,
  kebabMenu,
  kebabMenuOpen,
  setKebabMenuOpen,
  disableKebabHover,
  grey,
  hideTitle,
  href,
  onClick,
  children,
}: SidebarButtonProps) {
  const finalClassName = `w-full flex flex-row gap-spacing-interline py-spacing-interline px-padding-button hover:bg-background-tint-01 ${active && "bg-background-tint-00"} ${kebabMenuOpen && "bg-background-tint-01"} rounded-08 items-center group ${hideTitle && "justify-center"} ${className}`;

  const content = (
    <>
      {Icon && (
        <Icon
          className={`h-[1.2rem] min-w-[1.2rem] ${!hideTitle && "mr-[0.4rem]"} ${grey ? "stroke-text-02" : "stroke-text-03"}`}
        />
      )}
      {!hideTitle &&
        (typeof children === "string" ? (
          <Truncated>
            <Text text02={grey} text03={!grey}>
              {children}
            </Text>
          </Truncated>
        ) : (
          children
        ))}
      {!hideTitle && <div className="flex-1" />}
      {kebabMenu &&
        kebabMenuOpen !== undefined &&
        setKebabMenuOpen &&
        !hideTitle && (
          <Popover open={kebabMenuOpen} onOpenChange={setKebabMenuOpen}>
            <PopoverTrigger asChild>
              {!disableKebabHover && (
                <div
                  className={`relative h-[1.5rem]`}
                  onClick={(event) => {
                    event.stopPropagation();
                    setKebabMenuOpen((prev) => !prev);
                  }}
                >
                  <div
                    className={`h-[1.5rem] w-[1.5rem] ${kebabMenuOpen ? "flex" : "hidden group-hover:flex"}`}
                  />
                  <div
                    className={`absolute inset-0 w-full h-full flex flex-col justify-center items-center rounded-08 hover:bg-background-tint-00 ${kebabMenuOpen && "bg-background-tint-00"}`}
                  >
                    <SvgMoreHorizontal
                      className={`h-[1rem] min-w-[1rem] ${kebabMenuOpen ? "visible" : "invisible group-hover:visible"} stroke-text-03`}
                    />
                  </div>
                </div>
              )}
            </PopoverTrigger>
            <PopoverContent align="start" side="right">
              {kebabMenu}
            </PopoverContent>
          </Popover>
        )}
    </>
  );

  if (href)
    return (
      <Link className={finalClassName} href={href}>
        {content}
      </Link>
    );

  if (onClick)
    return (
      <button className={finalClassName} onClick={onClick}>
        {content}
      </button>
    );

  return <div className={finalClassName}>{content}</div>;
}

export interface SidebarSectionProps {
  title: string;
  children?: React.ReactNode;
}

export function SidebarSection({ title, children }: SidebarSectionProps) {
  return (
    <div className="flex flex-col gap-spacing-inline">
      <Text
        secondaryBody
        text02
        className="px-padding-button sticky top-[0rem] bg-background-tint-02 z-10 py-spacing-interline"
      >
        {title}
      </Text>
      <div>{children}</div>
    </div>
  );
}
