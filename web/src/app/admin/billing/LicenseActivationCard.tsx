"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Card } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import InputFile from "@/refresh-components/inputs/InputFile";
import { Section } from "@/layouts/general-layouts";
import { InputVertical } from "@opal/layouts";
import { SvgXCircle, SvgCheckCircle, SvgXOctagon } from "@opal/icons";
import { uploadLicense } from "@/lib/billing/svc";
import { LicenseStatus } from "@/lib/billing/interfaces";
import { formatDateShort } from "@/lib/dateUtils";

const BILLING_HELP_URL = "https://docs.onyx.app/admins/billing/overview";

interface LicenseActivationCardProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  license?: LicenseStatus;
  hideClose?: boolean;
}

export default function LicenseActivationCard({
  isOpen,
  onClose,
  onSuccess,
  license,
  hideClose,
}: LicenseActivationCardProps) {
  const t = useTranslations("admin.billing");
  const [licenseKey, setLicenseKey] = useState("");
  const [isActivating, setIsActivating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [showInput, setShowInput] = useState(!license?.has_license);

  const hasLicense = license?.has_license;
  const isDateExpired = license?.expires_at
    ? new Date(license.expires_at) < new Date()
    : false;
  const isExpired =
    license?.status === "expired" ||
    license?.status === "gated_access" ||
    isDateExpired;
  const expirationDate = license?.expires_at
    ? formatDateShort(license.expires_at)
    : null;

  const handleActivate = async () => {
    if (!licenseKey.trim()) {
      setError(t("license.emptyKey.error"));
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
        err instanceof Error ? err.message : t("license.activateFailed.error")
      );
    } finally {
      setIsActivating(false);
    }
  };

  const handleClose = () => {
    setLicenseKey("");
    setError(null);
    setSuccess(false);
    setShowInput(!license?.has_license);
    onClose();
  };

  if (!isOpen) return null;

  // License status view (when license exists and not editing)
  if (hasLicense && !showInput) {
    return (
      <Card border="solid" padding={4} rounding={4}>
        <Section alignItems="stretch" height="fit">
          <Section
            flexDirection="row"
            justifyContent="between"
            alignItems="center"
            height="auto"
          >
            <Section
              flexDirection="column"
              alignItems="start"
              gap={2}
              height="auto"
              width="auto"
            >
              {isExpired ? (
                <SvgXOctagon size={16} className="stroke-status-error-05" />
              ) : (
                <SvgCheckCircle
                  size={16}
                  className="stroke-status-success-05"
                />
              )}
              <Text secondaryBody text03>
                {isExpired
                  ? t("license.expired.label")
                  : t.rich("license.activeUntil.label", {
                      date: expirationDate ?? "",
                      value: (chunks) => (
                        <Text secondaryBody text04>
                          {chunks}
                        </Text>
                      ),
                    })}
              </Text>
            </Section>
            <Section flexDirection="row" gap={2} height="auto" width="auto">
              <Button prominence="secondary" onClick={() => setShowInput(true)}>
                {t("license.updateKey.label")}
              </Button>
              {!hideClose && (
                <Button prominence="tertiary" onClick={handleClose}>
                  {t("license.close.label")}
                </Button>
              )}
            </Section>
          </Section>
        </Section>
      </Card>
    );
  }

  // License input form
  return (
    <Card border="solid" padding={0} rounding={4}>
      <Section alignItems="stretch" height="fit" gap={0}>
        {/* Header */}
        <Section
          flexDirection="column"
          alignItems="stretch"
          gap={0}
          padding={4}
        >
          <Section
            flexDirection="row"
            justifyContent="between"
            alignItems="center"
          >
            <Text headingH3>
              {hasLicense
                ? t("license.updateTitle.title")
                : t("license.activateTitle.title")}
            </Text>
            <Button
              disabled={isActivating}
              prominence="secondary"
              onClick={handleClose}
            >
              {t("license.cancel.label")}
            </Button>
          </Section>
          <Text secondaryBody text03>
            {t("license.description")}
          </Text>
        </Section>

        {/* Content */}
        <div className="billing-content-area">
          <Section
            flexDirection="column"
            alignItems="stretch"
            gap={2}
            padding={4}
          >
            {success && (
              <div className="billing-success-message">
                <Text secondaryBody>
                  {hasLicense
                    ? t("license.updateSuccess.message")
                    : t("license.activateSuccess.message")}
                </Text>
              </div>
            )}

            <InputVertical
              title={t("license.keyField.title")}
              subDescription={
                error ? undefined : t("license.keyField.description")
              }
              withLabel
            >
              <InputFile
                placeholder="eyJwYXlsb2FkIjogeyJ2ZXJzaW9..."
                setValue={(value) => {
                  setLicenseKey(value);
                  setError(null);
                }}
                error={!!error}
              />
              {error && (
                <Section
                  flexDirection="row"
                  alignItems="center"
                  justifyContent="start"
                  gap={1}
                  height="auto"
                >
                  <div className="billing-error-icon">
                    <SvgXCircle size={12} />
                  </div>
                  <Text secondaryBody text04>
                    {t.rich("license.error.text", {
                      error,
                      link: (chunks) => (
                        <a
                          href={BILLING_HELP_URL}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="billing-help-link"
                        >
                          {chunks}
                        </a>
                      ),
                    })}
                  </Text>
                </Section>
              )}
            </InputVertical>
          </Section>
        </div>

        {/* Footer */}
        <Section flexDirection="row" justifyContent="end" padding={4}>
          <Button
            disabled={isActivating || !licenseKey.trim() || success}
            onClick={handleActivate}
          >
            {isActivating
              ? t("license.activating.label")
              : hasLicense
                ? t("license.updateLicense.label")
                : t("license.activateLicense.label")}
          </Button>
        </Section>
      </Section>
    </Card>
  );
}
