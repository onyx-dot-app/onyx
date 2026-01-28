"use client";

import { useState } from "react";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgClipboard, SvgX } from "@opal/icons";
import { uploadLicense } from "@/lib/billing/actions";

interface LicenseInputProps {
  onCancel: () => void;
  onSuccess?: () => void;
  onActivate?: (licenseKey: string) => Promise<void>;
}

export default function LicenseInput({
  onCancel,
  onSuccess,
  onActivate,
}: LicenseInputProps) {
  const [licenseKey, setLicenseKey] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText();
      setLicenseKey(text.trim());
      setError(null);
    } catch (err) {
      console.error("Failed to read clipboard:", err);
    }
  };

  const handleActivate = async () => {
    if (!licenseKey.trim()) {
      setError("Please enter a license key");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      if (onActivate) {
        await onActivate(licenseKey.trim());
      } else {
        await uploadLicense(licenseKey.trim());
      }
      onSuccess?.();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to activate license"
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Card>
      <Section gap={1} alignItems="start" height="auto">
        {/* Header with title and cancel button */}
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="start"
          height="auto"
        >
          <Section gap={0.25} alignItems="start" height="auto" width="auto">
            <Text mainContentEmphasis>Activate License Key</Text>
            <Text secondaryBody text03>
              Manually add and activate a license for this Onyx instance.
            </Text>
          </Section>
          <IconButton icon={SvgX} onClick={onCancel} main tertiary />
        </Section>

        {/* License key input */}
        <Section gap={0.5} alignItems="start" height="auto">
          <Text secondaryBody>License Key</Text>
          <InputTypeIn
            value={licenseKey}
            onChange={(e) => {
              setLicenseKey(e.target.value);
              setError(null);
            }}
            placeholder="64-character key string"
            className="billing-license-input"
            showClearButton={false}
            rightSection={
              <IconButton
                icon={SvgClipboard}
                onClick={handlePaste}
                main
                tertiary
              />
            }
          />
          <Text secondaryBody text03>
            Paste or attach your license key file you received from Onyx.
          </Text>
        </Section>

        {error && (
          <Text secondaryBody text02>
            {error}
          </Text>
        )}

        {/* Activate button */}
        <Button
          main
          primary
          onClick={handleActivate}
          disabled={isSubmitting || !licenseKey.trim()}
        >
          {isSubmitting ? "Activating..." : "Activate License"}
        </Button>
      </Section>
    </Card>
  );
}
