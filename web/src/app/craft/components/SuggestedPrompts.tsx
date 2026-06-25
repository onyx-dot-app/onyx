"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import { SvgX } from "@opal/icons";
import {
  useCaseDomains,
  UseCaseDomain,
} from "@/app/craft/constants/exampleBuildPrompts";

interface SuggestedPromptsProps {
  onPromptClick: (promptText: string) => void;
}

export default function SuggestedPrompts({
  onPromptClick,
}: SuggestedPromptsProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const expandedDomain: UseCaseDomain | undefined = useCaseDomains.find(
    (domain) => domain.id === expandedId
  );

  // Collapse the expanded panel when the user clicks anywhere outside it.
  useEffect(() => {
    if (expandedId === null) return;
    function handleOutsideClick(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setExpandedId(null);
      }
    }
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, [expandedId]);

  function handlePillClick(domainId: string) {
    setExpandedId((current) => (current === domainId ? null : domainId));
  }

  function handlePromptClick(fullText: string) {
    onPromptClick(fullText);
    setExpandedId(null);
  }

  return (
    <div
      ref={containerRef}
      className="relative mt-4 w-full flex flex-col items-center"
    >
      <div className="flex flex-row flex-wrap items-center justify-center gap-2">
        {useCaseDomains.map((domain) => (
          <button
            key={domain.id}
            type="button"
            onClick={() => handlePillClick(domain.id)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-12 px-3 py-2 cursor-pointer transition-colors",
              "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-action-link-01 focus-visible:ring-offset-2",
              expandedId === domain.id
                ? "bg-background-tint-01 text-text-05"
                : "text-text-03 hover:bg-background-tint-02 hover:text-text-04"
            )}
          >
            <domain.icon className="w-4 h-4" />
            <Text font="main-ui-body" color="inherit">
              {domain.label}
            </Text>
          </button>
        ))}
      </div>

      <AnimatePresence>
        {expandedDomain && (
          <motion.div
            key={expandedDomain.id}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="absolute top-full left-0 right-0 z-20 mt-3 w-full p-2"
          >
            <div className="flex items-center justify-between px-3 pt-2 pb-1">
              <div className="flex items-center gap-2">
                <expandedDomain.icon className="w-3.5 h-3.5 text-text-02" />
                <Text font="figure-small-label" color="text-02">
                  {expandedDomain.label}
                </Text>
              </div>
              <button
                type="button"
                onClick={() => setExpandedId(null)}
                aria-label="Close suggestions"
                className="flex items-center justify-center cursor-pointer"
              >
                <SvgX className="w-4 h-4 text-text-03" />
              </button>
            </div>

            <div className="flex flex-col">
              {expandedDomain.prompts.map((prompt) => (
                <button
                  key={prompt.id}
                  type="button"
                  onClick={() => handlePromptClick(prompt.fullText)}
                  className={cn(
                    "w-full rounded-12 px-3 py-2.5 text-left",
                    "hover:bg-background-tint-02",
                    "transition-colors cursor-pointer",
                    "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-action-link-01 focus-visible:ring-offset-2"
                  )}
                >
                  <Text font="main-content-body" color="text-04">
                    {prompt.summary}
                  </Text>
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
