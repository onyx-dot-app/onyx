"use client";

// This should be used as the header for *all* pages (including admin pages).

import type { IconProps } from "@opal";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { useEffect, useRef, useState } from "react";

export interface PageHeaderProps {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description: string;
  className?: string;
  children?: React.ReactNode;
  rightChildren?: React.ReactNode;
}

export default function PageHeader({
  icon: Icon,
  title,
  description,
  className,
  children,
  rightChildren,
}: PageHeaderProps) {
  const [showShadow, setShowShadow] = useState(false);
  const headerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // IMPORTANT: This component relies on PageWrapper.tsx having the ID "page-wrapper-scroll-container"
    // on its scrollable container. If that ID is removed or changed, the scroll shadow will not work.
    // See PageWrapper.tsx for more details.
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
    <div ref={headerRef} className={cn("pt-10 sticky top-0 z-10", className)}>
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
          // If you want to implement a radial scroll-shadow, you can apply the bottom line.
          // I tried playing around with this here, but wasn't able to find a configuration that just *hit the spot*...
          // - @raunakab
          //
          // background:
          //   "radial-gradient(ellipse 50% 80% at 50% 0%, var(--mask-03), transparent)",
        }}
      />
    </div>
  );
}
