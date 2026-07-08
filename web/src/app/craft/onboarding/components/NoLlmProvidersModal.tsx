"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Text } from "@opal/components";
import { SvgLock, SvgArrowRight } from "@opal/icons";
import { logout } from "@/lib/users/svc";
import { cn } from "@opal/utils";

interface NoLlmProvidersModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Modal shown to non-admin users when no LLM providers are configured.
 * Explains that an admin needs to configure providers before they can use Craft.
 */
export default function NoLlmProvidersModal({
  open,
  onClose,
}: NoLlmProvidersModalProps) {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);

  const handleCreateNewAccount = async () => {
    setIsLoading(true);
    try {
      await logout();
      router.push("/auth/signup");
    } finally {
      setIsLoading(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-xs" />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-xl mx-4 bg-background-tint-01 rounded-16 shadow-lg border border-border-01">
        <div className="p-6 flex flex-col gap-6 min-h-[400px]">
          {/* Content */}
          <div className="flex-1 flex flex-col items-center justify-center gap-6">
            {/* Icon */}
            <div className="w-16 h-16 rounded-full bg-background-tint-02 flex items-center justify-center">
              <SvgLock className="w-8 h-8 text-text-03" />
            </div>

            {/* Header */}
            <div className="flex flex-col items-center gap-2 text-center max-w-sm">
              <Text font="heading-h2" color="text-05">
                LLM Provider Required
              </Text>
              <Text font="main-ui-body" color="text-03">
                Onyx Craft requires an LLM provider to be configured, but only
                admins can set this up.
              </Text>
              <Text font="main-ui-body" color="text-03">
                Please ask your admin to configure an LLM provider, or create a
                new Onyx account to become an admin yourself!
              </Text>
            </div>
          </div>

          {/* Footer buttons */}
          <div className="flex justify-center gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex items-center gap-1.5 px-4 py-2 rounded-12 border border-border-01 bg-background-tint-00 text-text-04 hover:bg-background-tint-02 transition-colors"
            >
              <Text font="main-ui-action" color="text-05">
                Go Back
              </Text>
            </button>
            <button
              type="button"
              onClick={handleCreateNewAccount}
              disabled={isLoading}
              className={cn(
                "flex items-center gap-1.5 px-4 py-2 rounded-12 transition-colors",
                !isLoading
                  ? "bg-black dark:bg-white text-white dark:text-black hover:opacity-90"
                  : "bg-background-neutral-01 text-text-02 cursor-not-allowed"
              )}
            >
              <Text
                font="main-ui-action"
                color={!isLoading ? "text-inverted-05" : "text-02"}
              >
                {isLoading ? "Signing out..." : "Create a new account"}
              </Text>
              {!isLoading && (
                <SvgArrowRight className="w-4 h-4 text-white dark:text-black" />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
