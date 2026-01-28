"use client";

import { useRouter } from "next/navigation";
import Text from "@/refresh-components/texts/Text";
import { SvgArrowRight } from "@opal/icons";
import { UsageLimits } from "@/app/craft/types/streamingTypes";
import type { Route } from "next";

interface UpgradePlanModalProps {
  open: boolean;
  onClose: () => void;
  limits: UsageLimits | null;
}

/**
 * Modal shown when users hit their message limit on a free trial plan.
 * Encourages upgrading to a paid plan for more messages.
 */
export default function UpgradePlanModal({
  open,
  onClose,
  limits,
}: UpgradePlanModalProps) {
  const router = useRouter();

  const handleUpgrade = () => {
    router.push("/admin/billing" as Route);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      <div className="relative z-10 w-full max-w-xl mx-4 bg-background-tint-01 rounded-16 shadow-lg border border-border-01">
        <div className="p-6 flex flex-col gap-6 min-h-[400px]">
          <div className="flex-1 flex flex-col items-center justify-center gap-6">
            <img
              src="/upgrade_modal_icon.png"
              alt="Upgrade"
              className="w-32 h-32"
            />

            <div className="flex flex-col items-center gap-2 text-center">
              <Text headingH2 text05>
                You've reached your message limit
              </Text>
              <Text mainUiBody text03 className="max-w-sm">
                You've used all {limits?.limit ?? 5} messages in your free
                trial.
                <br />
                <br />
                Upgrade to keep crafting with Onyx and unlock more messages per
                week.
              </Text>
            </div>
          </div>

          <div className="flex justify-center gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex items-center gap-1.5 px-4 py-2 rounded-12 border border-border-01 bg-background-tint-00 text-text-04 hover:bg-background-tint-02 transition-colors"
            >
              <Text mainUiAction>Maybe Later</Text>
            </button>
            <button
              type="button"
              onClick={handleUpgrade}
              className="flex items-center gap-1.5 px-4 py-2 rounded-12 bg-black dark:bg-white text-white dark:text-black hover:opacity-90 transition-colors"
            >
              <Text mainUiAction className="text-white dark:text-black">
                Upgrade
              </Text>
              <SvgArrowRight className="w-4 h-4 text-white dark:text-black" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
