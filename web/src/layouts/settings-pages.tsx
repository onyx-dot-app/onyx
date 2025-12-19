"use client";

import { cn } from "@/lib/utils";
import BackButton from "@/refresh-components/buttons/BackButton";
import Text from "@/refresh-components/texts/Text";
import { IconProps } from "@opal/types";
import { useEffect, useRef, useState } from "react";

export interface SettingsRootProps
  extends React.HtmlHTMLAttributes<HTMLDivElement> {}

function SettingsRoot(props: SettingsRootProps) {
  return (
    <div
      id="page-wrapper-scroll-container"
      className="w-full h-full flex flex-col items-center overflow-y-auto"
    >
      {/* WARNING: The id="page-wrapper-scroll-container" above is used by SettingsHeader
          to detect scroll position and show/hide the scroll shadow.
          DO NOT REMOVE this ID without updating SettingsHeader accordingly. */}
      <div className="h-full w-[min(50rem,100%)]">
        <div {...props} />
      </div>
    </div>
  );
}

export interface SettingsHeaderProps {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description: string;
  className?: string;
  children?: React.ReactNode;
  rightChildren?: React.ReactNode;
  renderBackButton?: boolean;
}

function SettingsHeader({
  icon: Icon,
  title,
  description,
  className,
  children,
  rightChildren,
  renderBackButton,
}: SettingsHeaderProps) {
  const [showShadow, setShowShadow] = useState(false);
  const headerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // IMPORTANT: This component relies on SettingsRoot having the ID "page-wrapper-scroll-container"
    // on its scrollable container. If that ID is removed or changed, the scroll shadow will not work.
    const scrollContainer = document.getElementById(
      "page-wrapper-scroll-container"
    );
    if (!scrollContainer) return;

    const handleScroll = () => {
      // Show shadow if the scroll container has been scrolled down
      setShowShadow(scrollContainer.scrollTop > 0);
    };

    scrollContainer.addEventListener("scroll", handleScroll);
    handleScroll(); // Check initial state

    return () => scrollContainer.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <div
      ref={headerRef}
      className={cn("pt-10 sticky top-0 z-10 w-full", className)}
    >
      {renderBackButton && <BackButton />}
      <div className="flex flex-col gap-6 px-4 pt-4 pb-2">
        <div className="flex flex-col">
          <div className="flex flex-row justify-between items-center gap-4">
            <Icon className="stroke-text-04 h-[1.75rem] w-[1.75rem]" />
            {rightChildren}
          </div>
          <div className="flex flex-col">
            <Text headingH2>{title}</Text>
            <Text secondaryBody text03>
              {description}
            </Text>
          </div>
        </div>
        <div>{children}</div>
      </div>
      <div
        className={cn(
          "absolute left-0 right-0 h-[0.5rem] pointer-events-none transition-opacity duration-300 rounded-b-08 opacity-0",
          showShadow && "opacity-100"
        )}
        style={{
          background: "linear-gradient(to bottom, var(--mask-02), transparent)",
        }}
      />
    </div>
  );
}

export interface SettingsBodyProps
  extends React.HtmlHTMLAttributes<HTMLDivElement> {}

function SettingsBody({ className, ...props }: SettingsBodyProps) {
  return (
    <div
      className={cn("py-6 px-4 flex flex-col gap-8 w-full", className)}
      {...props}
    />
  );
}

const Settings = {
  Root: SettingsRoot,
  Header: SettingsHeader,
  Body: SettingsBody,
};

export default Settings;
