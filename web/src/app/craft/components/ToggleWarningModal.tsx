"use client";

import { Text } from "@opal/components";
import { markdown } from "@opal/utils";

interface ToggleWarningModalProps {
  open: boolean;
  recommendedModelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ToggleWarningModal({
  open,
  recommendedModelLabel,
  onConfirm,
  onCancel,
}: ToggleWarningModalProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-1400 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-xs"
        onClick={(e) => {
          e.stopPropagation();
          onCancel();
        }}
      />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-xl mx-4 bg-background-tint-01 rounded-16 shadow-lg border border-border-01">
        <div className="p-6 flex flex-col gap-6">
          {/* Header */}
          <div className="flex items-center justify-center">
            <Text font="heading-h2" color="text-05">
              Show all models?
            </Text>
          </div>

          {/* Message */}
          <div className="flex justify-center text-center">
            <Text font="main-ui-body" color="text-04">
              {markdown(
                `We recommend using **${recommendedModelLabel}** for Crafting.\nOther models may have reduced capabilities for code creation,\ndata analysis, and artifact creation.`
              )}
            </Text>
          </div>

          {/* Action buttons */}
          <div className="flex items-center justify-center gap-3">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onConfirm();
              }}
              className="px-4 py-2 rounded-12 bg-background-neutral-01 border border-border-02 hover:opacity-90 transition-colors"
            >
              <Text font="main-ui-body" color="text-05">
                Show All Models
              </Text>
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onCancel();
              }}
              className="px-4 py-2 rounded-12 bg-black dark:bg-white hover:opacity-90 transition-colors"
            >
              <Text font="main-ui-action" color="text-inverted-05">
                Keep Recommended
              </Text>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
