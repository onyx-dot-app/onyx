"use client";

import { useState } from "react";
import { track, AnalyticsEvent } from "@/lib/analytics/utils";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import { OnboardingModalMode } from "@/app/craft/onboarding/types";
import OnboardingInfoPages from "@/app/craft/onboarding/components/OnboardingInfoPages";

interface BuildOnboardingModalProps {
  mode: OnboardingModalMode;
  onComplete: () => Promise<void>;
  onClose: () => void;
}

/**
 * First-visit intro modal. Provider setup lives inline on the welcome page
 * (CraftLlmSetup), so this is intro-only.
 */
export default function BuildOnboardingModal({
  mode,
  onComplete,
  onClose,
}: BuildOnboardingModalProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (mode.type === "closed") return null;

  const handleSubmit = async () => {
    setIsSubmitting(true);

    try {
      await onComplete();
      track(AnalyticsEvent.COMPLETED_CRAFT_ONBOARDING);
      onClose();
    } catch (error) {
      console.error("Error completing onboarding:", error);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-xs" />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-xl mx-4 bg-background-tint-01 rounded-16 shadow-lg border border-border-01">
        <div className="p-6 flex flex-col gap-6 min-h-[600px]">
          <OnboardingInfoPages step="page1" />

          <div className="flex justify-end items-center pt-2">
            <button
              type="button"
              onClick={handleSubmit}
              disabled={isSubmitting}
              className={cn(
                "flex items-center gap-1.5 px-4 py-2 rounded-12 transition-colors",
                !isSubmitting
                  ? "bg-black dark:bg-white text-white dark:text-black hover:opacity-90"
                  : "bg-background-neutral-01 text-text-02 cursor-not-allowed"
              )}
            >
              <Text
                font="main-ui-action"
                color={!isSubmitting ? "text-inverted-05" : "text-02"}
              >
                {isSubmitting ? "Saving..." : "Get Started!"}
              </Text>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
