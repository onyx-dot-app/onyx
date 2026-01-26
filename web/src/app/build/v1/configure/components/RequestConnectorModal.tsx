"use client";

import { useState } from "react";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

interface RequestConnectorModalProps {
  open: boolean;
  onClose: () => void;
}

export default function RequestConnectorModal({
  open,
  onClose,
}: RequestConnectorModalProps) {
  const [connectorName, setConnectorName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const handleClose = () => {
    setConnectorName("");
    setErrorMessage(null);
    setSuccessMessage(null);
    onClose();
  };

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!connectorName.trim()) return;

    setIsSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const response = await fetch("/api/manage/connector-request", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          connector_name: connectorName.trim(),
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to submit connector request");
      }

      setSuccessMessage(
        data.message ||
          "Connector request submitted successfully. We'll prioritize popular requests!"
      );

      setTimeout(() => {
        handleClose();
      }, 2000);
    } catch (error) {
      console.error("Failed to submit connector request:", error);
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "Failed to submit connector request. Please try again."
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!open) return null;

  const isCloud = NEXT_PUBLIC_CLOUD_ENABLED;
  const DISCORD_URL = "https://discord.gg/4NA5SbzrWb";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={handleClose}
      />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-xl mx-4 bg-background-tint-01 rounded-16 shadow-lg border border-border-01">
        <div className="p-6 flex flex-col gap-6">
          <div className="flex items-center justify-center">
            <Text headingH2 text05>
              Request a Connector
            </Text>
          </div>

          <div className="flex flex-col gap-3">
            <Text mainUiBody text04 className="text-center">
              Let us know which connectors you'd like to craft with
              <br />
              We'll prioritize popular requests!
            </Text>

            {successMessage && (
              <div className="px-4 py-3 rounded-12 bg-status-success-00 border border-status-success-02">
                <Text mainUiBody text05 className="text-status-success-05">
                  {successMessage}
                </Text>
              </div>
            )}

            {errorMessage && (
              <div className="px-4 py-3 rounded-12 bg-status-error-00 border border-status-error-02">
                <Text mainUiBody text05 className="text-status-error-05">
                  {errorMessage}
                </Text>
              </div>
            )}

            {isCloud ? (
              // Cloud: Show form with text input
              <>
                <form
                  onSubmit={handleSubmit}
                  className="flex flex-col gap-4 items-center"
                >
                  <input
                    id="connector-name"
                    type="text"
                    value={connectorName}
                    onChange={(e) => {
                      setConnectorName(e.target.value);
                      if (errorMessage) setErrorMessage(null);
                    }}
                    placeholder="e.g., ServiceNow, Workday, etc."
                    className="px-4 py-2 rounded-12 bg-background-tint-00 border border-border-01 text-text-05 placeholder:text-text-02 focus:outline-none focus:ring-2 focus:ring-border-01 text-center max-w-md w-full"
                    disabled={isSubmitting || !!successMessage}
                  />
                </form>

                <div className="flex items-center justify-center gap-3 pt-2 max-w-md w-full mx-auto">
                  <button
                    type="button"
                    onClick={handleClose}
                    disabled={isSubmitting}
                    className="flex-1 px-4 py-2 rounded-12 bg-background-neutral-01 border border-border-02 hover:opacity-90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Text mainUiBody text05>
                      {successMessage ? "Close" : "Cancel"}
                    </Text>
                  </button>
                  {!successMessage && (
                    <button
                      type="button"
                      onClick={handleSubmit}
                      disabled={!connectorName.trim() || isSubmitting}
                      className={cn(
                        "flex-1 px-4 py-2 rounded-12 transition-colors",
                        !connectorName.trim() || isSubmitting
                          ? "bg-background-neutral-01 text-text-02 cursor-not-allowed"
                          : "bg-black dark:bg-white hover:opacity-90"
                      )}
                    >
                      <Text
                        mainUiAction
                        className={
                          !connectorName.trim() || isSubmitting
                            ? "text-text-02"
                            : "text-text-light-05 dark:text-text-dark-05"
                        }
                      >
                        {isSubmitting ? "Submitting..." : "Submit Request"}
                      </Text>
                    </button>
                  )}
                </div>
              </>
            ) : (
              // Self-hosted: Show email link and Discord button
              <>
                <div className="flex flex-col gap-4 items-center">
                  <Text mainUiBody text04 className="text-center">
                    Email your request to{" "}
                    <a
                      href="mailto:hello@onyx.app?subject=Onyx Craft Connector Request"
                      className="text-blue-600 dark:text-blue-400 hover:underline"
                    >
                      hello@onyx.app
                    </a>
                  </Text>
                </div>

                <div className="flex items-center justify-center gap-3 pt-2 max-w-md w-full mx-auto">
                  <button
                    type="button"
                    onClick={handleClose}
                    className="flex-1 px-4 py-2 rounded-12 bg-background-neutral-01 border border-border-02 hover:opacity-90 transition-colors"
                  >
                    <Text mainUiBody text05>
                      Close
                    </Text>
                  </button>
                  <a
                    href={DISCORD_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex-1 px-4 py-2 rounded-12 bg-black dark:bg-white hover:opacity-90 transition-colors text-center"
                  >
                    <Text
                      mainUiAction
                      className="text-text-light-05 dark:text-text-dark-05"
                    >
                      Join Onyx Discord
                    </Text>
                  </a>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
