"use client";

import { Text } from "@opal/components";
import { SvgArrowUp, SvgPlus } from "@opal/icons";
import { cn } from "@opal/utils";
import { Logo } from "@/lib/app/components";

interface WelcomePageMockProps {
  /** Overlay content (e.g. a modal) rendered on top of the page. */
  children?: React.ReactNode;
  /**
   * Replaces the suggested-prompts area below the input (the slot inline
   * onboarding concepts occupy). Omit to show the default prompt pills.
   */
  bottomSlot?: React.ReactNode;
  /** Dims the page skeleton, e.g. while an overlay is up. */
  dimmed?: boolean;
}

/**
 * Static, context-free lookalike of the craft welcome page (BuildWelcome),
 * for presenting onboarding explorations in Storybook exactly where they
 * would appear on /craft/v1. Purely presentational.
 */
export default function WelcomePageMock({
  children,
  bottomSlot,
  dimmed = false,
}: WelcomePageMockProps) {
  return (
    <div className="relative w-full h-screen bg-background-tint-00 overflow-hidden">
      <div
        className={cn(
          "h-full grid px-4 transition-opacity",
          dimmed && "opacity-60"
        )}
        style={{ gridTemplateRows: "1fr auto 1fr" }}
      >
        {/* Wordmark + model pill */}
        <div className="row-start-1 min-h-0 w-full flex flex-col items-center justify-end">
          <div className="w-full max-w-3xl">
            <div className="flex flex-row items-center justify-between gap-4 pb-6">
              <div className="flex flex-row items-baseline gap-2 select-none">
                <Logo onyxBranded size={28} className="translate-y-[6px]" />
                <span
                  className="text-text-05"
                  style={{
                    fontFamily: "var(--font-kh-teka)",
                    fontWeight: 400,
                    fontSize: "34px",
                    lineHeight: "1",
                    letterSpacing: "-0.02em",
                  }}
                >
                  craft
                </span>
              </div>
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-12 border border-border-01 bg-background-tint-00">
                <div className="w-4 h-4 rounded-full bg-theme-primary-05" />
                <Text font="main-ui-body" color="text-04">
                  Claude Opus 4.8
                </Text>
              </div>
            </div>
          </div>
        </div>

        {/* Input bar */}
        <div className="row-start-2 w-full flex flex-col items-center">
          <div className="w-full max-w-3xl">
            <div className="flex flex-col gap-3 p-4 rounded-16 border border-border-01 bg-background-tint-00 shadow-sm">
              <Text font="main-content-body" color="text-02">
                Analyze my data and create a dashboard...
              </Text>
              <div className="flex items-center justify-between">
                <SvgPlus className="w-5 h-5 stroke-text-03" />
                <div className="flex items-center justify-center w-8 h-8 rounded-full bg-background-neutral-01">
                  <SvgArrowUp className="w-4 h-4 stroke-text-02" />
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Bottom slot: suggested prompts by default */}
        <div className="row-start-3 min-h-0 w-full flex flex-col items-center">
          <div className="w-full max-w-3xl">
            {bottomSlot ?? (
              <div className="mt-4 flex flex-row flex-wrap items-center justify-center gap-2">
                {["Engineering", "Sales", "Marketing", "Product"].map(
                  (label) => (
                    <div
                      key={label}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-12 border border-border-01 bg-background-tint-00"
                    >
                      <Text font="main-ui-body" color="text-04">
                        {label}
                      </Text>
                    </div>
                  )
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {children}
    </div>
  );
}
