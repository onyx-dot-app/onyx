"use client";

import Text from "@/refresh-components/texts/Text";

interface DemoDataConfirmModalProps {
  open: boolean;
  onClose: () => void;
  pendingDemoDataEnabled: boolean | null;
  onConfirm: () => void;
}

export default function DemoDataConfirmModal({
  open,
  onClose,
  pendingDemoDataEnabled,
  onConfirm,
}: DemoDataConfirmModalProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-xl mx-4 bg-background-tint-01 rounded-16 shadow-lg border border-border-01">
        <div className="p-6 flex flex-col gap-6">
          {/* Header */}
          <div className="flex items-center justify-center">
            <Text headingH2 text05>
              Confirm Demo Data Change
            </Text>
          </div>

          {/* Message */}
          <div className="flex justify-center">
            <Text mainUiBody text04 className="text-center">
              Are you sure you want to{" "}
              {pendingDemoDataEnabled ? "enable" : "disable"} demo data?
              <br />
              Your sandbox will be re-initialized with your new data set
            </Text>
          </div>

          {/* Action buttons */}
          <div className="flex items-center justify-center gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-12 bg-background-neutral-01 border border-border-02 hover:opacity-90 transition-colors"
            >
              <Text mainUiBody text05>
                Cancel
              </Text>
            </button>
            <button
              type="button"
              onClick={onConfirm}
              className="px-4 py-2 rounded-12 bg-black dark:bg-white hover:opacity-90 transition-colors"
            >
              <Text
                mainUiAction
                className="text-text-light-05 dark:text-text-dark-05"
              >
                Confirm
              </Text>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
