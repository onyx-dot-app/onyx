import { ChevronDown } from "lucide-react";
import React, { useState, ReactNode, useRef, useLayoutEffect } from "react";

interface CollapsibleCardProps {
  header: JSX.Element;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}

/**
 * Renders a "collapsible" card which, when collapsed, is meant to showcase very "high-level" information (e.g., the name), but when expanded, can show a list of sub-items which are all related to one another.
 */
export default function CollapsibleCard({
  header,
  children,
  defaultOpen = false,
  className = "",
}: CollapsibleCardProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [maxHeight, setMaxHeight] = useState<string | undefined>(undefined);
  const contentRef = useRef<HTMLDivElement>(null);

  // Update maxHeight for animation when open/close
  useLayoutEffect(() => {
    if (open && contentRef.current) {
      setMaxHeight(contentRef.current.scrollHeight + "px");
    } else {
      setMaxHeight("0px");
    }
  }, [open, children]);

  // If content changes size while open, update maxHeight
  useLayoutEffect(() => {
    if (open && contentRef.current) {
      const handleResize = () => {
        setMaxHeight(contentRef.current!.scrollHeight + "px");
      };
      handleResize();
      window.addEventListener("resize", handleResize);
      return () => window.removeEventListener("resize", handleResize);
    }
  }, [open, children]);

  return (
    <div
      className={`rounded-lg border border-border bg-background shadow-md transition-all ${className}`}
    >
      <button
        type="button"
        className="w-full flex items-center px-8 py-6 text-left focus:outline-none focus:ring-2 focus:ring-accent rounded-t-lg bg-accent-background hover:bg-accent-background-hovered transition-colors"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        <div className="flex-1">{header}</div>
        <span
          className="ml-3 transition-transform flex-shrink-0"
          style={{ transform: open ? "rotate(0deg)" : "rotate(-90deg)" }}
        >
          <ChevronDown size={20} />
        </span>
      </button>
      <div
        ref={contentRef}
        style={{
          maxHeight,
          opacity: open ? 1 : 0,
          overflow: "hidden",
          transition:
            "max-height 0.35s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
        }}
        aria-hidden={!open}
      >
        <div className="border-t border-border bg-background rounded-b-lg">
          {children}
        </div>
      </div>
    </div>
  );
}
