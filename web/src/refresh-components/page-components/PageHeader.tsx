"use client";

// This should be used as the header for *all* pages (including admin pages).

import { SvgProps } from "@/icons";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { useEffect, useRef, useState } from "react";

export interface PageHeaderProps {
  icon: React.FunctionComponent<SvgProps>;
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
    const handleScroll = () => {
      if (headerRef.current) {
        const headerBottom = headerRef.current.getBoundingClientRect().bottom;
        const viewportHeight = window.innerHeight;

        // Show shadow if there's content scrolled beneath the header
        setShowShadow(headerBottom < viewportHeight);
      }
    };

    window.addEventListener("scroll", handleScroll);
    handleScroll(); // Check initial state

    return () => window.removeEventListener("scroll", handleScroll);
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
          "absolute left-0 right-0 h-[1rem] pointer-events-none transition-opacity duration-200",
          showShadow ? "opacity-100" : "opacity-0"
        )}
        style={{
          background: "linear-gradient(to bottom, var(--mask-02), transparent)",
        }}
      />
    </div>
  );
}
