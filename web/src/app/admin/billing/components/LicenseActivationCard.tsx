"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { uploadLicense } from "@/lib/billing/actions";

interface LicenseActivationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  isUpdate?: boolean;
}

export default function LicenseActivationInput({
  isOpen,
  onClose,
  onSuccess,
  isUpdate,
}: LicenseActivationModalProps) {
  const [licenseKey, setLicenseKey] = useState("");
  const [isActivating, setIsActivating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleActivate = async () => {
    if (!licenseKey.trim()) {
      setError("Please enter a license key");
      return;
    }

    setIsActivating(true);
    setError(null);

    try {
      await uploadLicense(licenseKey.trim());
      setSuccess(true);
      setTimeout(() => {
        onSuccess();
        handleClose();
      }, 1000);
    } catch (err) {
      console.error("Error activating license:", err);
      setError(
        err instanceof Error ? err.message : "Failed to activate license"
      );
    } finally {
      setIsActivating(false);
    }
  };

  const handleClose = () => {
    setLicenseKey("");
    setError(null);
    setSuccess(false);
    onClose();
  };

  if (!isOpen) return null;

  return (
    <Card className="w-full">
      {/* Header */}
      <div className="flex flex-col gap-1 p-4">
        <div className="flex items-center justify-between">
          <Text headingH3>
            {isUpdate ? "Update License Key" : "Activate License Key"}
          </Text>
          <Button tertiary onClick={handleClose} disabled={isActivating}>
            Cancel
          </Button>
        </div>
        <Text secondaryBody text03>
          Enter your 64-character license key to{" "}
          {isUpdate ? "update your license" : "activate premium features"}
        </Text>
      </div>

      {/* Content */}
      <div className="flex flex-col gap-2 p-4 bg-background-tint-01">
        {/* Success message */}
        {success && (
          <div className="w-full p-3 bg-status-success-01 border border-status-success-02 rounded-lg">
            <Text secondaryBody className="text-status-success-05">
              License {isUpdate ? "updated" : "activated"} successfully!
            </Text>
          </div>
        )}

        <Text secondaryBody text02>
          License Key
        </Text>
        <input
          type="text"
          value={licenseKey}
          onChange={(e) => {
            setLicenseKey(e.target.value);
            setError(null);
          }}
          placeholder="64-character key string"
          className="w-full p-3 border border-border-01 rounded-lg bg-background-neutral-00 text-text-01 font-mono text-sm focus:outline-none focus:border-action-link-05"
        />
        <Text secondaryBody text03>
          Find your license key in your purchase confirmation email
        </Text>

        {/* Error message */}
        {error && (
          <Text secondaryBody className="text-status-error-05">
            {error}
          </Text>
        )}
      </div>

      {/* Footer */}
      <div className="flex justify-end p-4">
        <Button
          main
          primary
          onClick={handleActivate}
          disabled={isActivating || !licenseKey.trim() || success}
        >
          {isActivating
            ? "Activating..."
            : isUpdate
              ? "Update License"
              : "Activate License"}
        </Button>
      </div>
    </Card>
  );
}
