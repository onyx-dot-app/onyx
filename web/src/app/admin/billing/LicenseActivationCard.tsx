"use client";

import { useState } from "react";
import Card from "@/refresh-components/cards/Card";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import InputFile from "@/refresh-components/inputs/InputFile";
import { Section } from "@/layouts/general-layouts";
import { InputVertical } from "@opal/layouts";
import { SvgXCircle, SvgCheckCircle, SvgXOctagon } from "@opal/icons";
import { uploadLicense } from "@/lib/billing/svc";
import { LicenseStatus } from "@/lib/billing/interfaces";
import { formatDateShort } from "@/lib/dateUtils";

const BILLING_HELP_URL = "https://docs.glomi.ai/admins/billing/overview";

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
      setError("请输入许可证 Key");
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
        err instanceof Error ? err.message : "激活许可证失败"
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
      <Card padding={1} alignItems="stretch">
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          height="auto"
        >
          <Section
            flexDirection="column"
            alignItems="start"
            gap={0.5}
            height="auto"
            width="auto"
          >
            {isExpired ? (
              <SvgXOctagon size={16} className="stroke-status-error-05" />
            ) : (
              <SvgCheckCircle size={16} className="stroke-status-success-05" />
            )}
            <Text secondaryBody text03>
              {isExpired ? (
                <>许可证 Key 已过期</>
              ) : (
                <>
                  许可证 Key 有效期至{" "}
                  <Text secondaryBody text04>
                    {expirationDate}
                  </Text>
                </>
              )}
            </Text>
          </Section>
          <Section flexDirection="row" gap={0.5} height="auto" width="auto">
            <Button prominence="secondary" onClick={() => setShowInput(true)}>
              更新 Key
            </Button>
            {!hideClose && (
              <Button prominence="tertiary" onClick={handleClose}>
                关闭
              </Button>
            )}
          </Section>
        </Section>
      </Card>
    );
  }

  // License input form
  return (
    <Card padding={0} alignItems="stretch" gap={0}>
      {/* Header */}
      <Section flexDirection="column" alignItems="stretch" gap={0} padding={1}>
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
        >
          <Text headingH3>
            {hasLicense ? "更新许可证 Key" : "激活许可证 Key"}
          </Text>
          <Button
            disabled={isActivating}
            prominence="secondary"
            onClick={handleClose}
          >
            取消
          </Button>
        </Section>
        <Text secondaryBody text03>
          为此 Glomi AI 实例手动添加并激活许可证。
        </Text>
      </Section>

      {/* Content */}
      <div className="billing-content-area">
        <Section
          flexDirection="column"
          alignItems="stretch"
          gap={0.5}
          padding={1}
        >
          {success && (
            <div className="billing-success-message">
              <Text secondaryBody>
                许可证已成功{hasLicense ? "更新" : "激活"}！
              </Text>
            </div>
          )}

          <InputVertical
            title="许可证 Key"
            subDescription={
              error
                ? undefined
                : "粘贴或附加你从 Glomi AI 收到的许可证 Key 文件。"
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
                gap={0.25}
                height="auto"
              >
                <div className="billing-error-icon">
                  <SvgXCircle size={12} />
                </div>
                <Text secondaryBody text04>
                  {error}.{" "}
                  <a
                    href={BILLING_HELP_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="billing-help-link"
                  >
                    计费帮助
                  </a>
                </Text>
              </Section>
            )}
          </InputVertical>
        </Section>
      </div>

      {/* Footer */}
      <Section flexDirection="row" justifyContent="end" padding={1}>
        <Button
          disabled={isActivating || !licenseKey.trim() || success}
          onClick={handleActivate}
        >
          {isActivating
            ? "正在激活..."
            : hasLicense
              ? "更新许可证"
              : "激活许可证"}
        </Button>
      </Section>
    </Card>
  );
}
