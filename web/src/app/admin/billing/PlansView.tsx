"use client";

import {
  SvgDashboard,
  SvgHistory,
  SvgFiles,
  SvgGlobe,
  SvgHardDrive,
  SvgHeadsetMic,
  SvgShareWebhook,
  SvgKey,
  SvgLock,
  SvgPaintBrush,
  SvgOrganization,
  SvgServer,
  SvgShield,
  SvgSliders,
  SvgUserManage,
  SvgUsers,
} from "@opal/icons";
import "@/app/admin/billing/billing.css";
import type { IconProps } from "@opal/types";
import Card from "@/refresh-components/cards/Card";
import Button from "@/refresh-components/buttons/Button";
import { Button as OpalButton } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";
import { useTranslations } from "next-intl";

const SALES_URL = "https://www.onyx.app/contact-sales";

// ----------------------------------------------------------------------------
// Types
// ----------------------------------------------------------------------------

interface PlanFeature {
  icon: React.FunctionComponent<IconProps>;
  textKey: string;
}

interface PlanConfig {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  pricing?: string;
  description: string;
  buttonLabel: string;
  buttonVariant: "primary" | "secondary";
  buttonIcon?: React.FunctionComponent<IconProps>;
  onClick?: () => void;
  href?: string;
  features: PlanFeature[];
  featuresPrefix: string;
  isCurrentPlan?: boolean;
}

// ----------------------------------------------------------------------------
// Plan Features
// ----------------------------------------------------------------------------

const BUSINESS_FEATURES: PlanFeature[] = [
  { icon: SvgFiles, textKey: "inheritPermissions" },
  { icon: SvgHistory, textKey: "queryHistory" },
  { icon: SvgShield, textKey: "rbac" },
  { icon: SvgLock, textKey: "encryptionSecrets" },
  { icon: SvgKey, textKey: "apiKeys" },
  { icon: SvgHardDrive, textKey: "selfHosting" },
  { icon: SvgPaintBrush, textKey: "customTheming" },
];

const ENTERPRISE_FEATURES: PlanFeature[] = [
  { icon: SvgUsers, textKey: "scimSync" },
  { icon: SvgDashboard, textKey: "whiteLabeling" },
  { icon: SvgUserManage, textKey: "customRoles" },
  { icon: SvgSliders, textKey: "usageLimits" },
  { icon: SvgShareWebhook, textKey: "hookExtensions" },
  { icon: SvgServer, textKey: "customDeployments" },
  { icon: SvgGlobe, textKey: "regionData" },
  { icon: SvgHeadsetMic, textKey: "enterpriseSla" },
];

// ----------------------------------------------------------------------------
// PlanCard (inlined)
// ----------------------------------------------------------------------------

function PlanCard({
  icon: Icon,
  title,
  pricing,
  description,
  buttonLabel,
  buttonIcon: ButtonIcon,
  onClick,
  href,
  features,
  featuresPrefix,
  isCurrentPlan,
  hideFeatures,
}: PlanConfig & { hideFeatures?: boolean }) {
  const t = useTranslations("admin.billing");

  return (
    <Card
      padding={0}
      gap={0}
      alignItems="stretch"
      aria-label={title + " plan card"}
      className="plan-card"
    >
      <Section
        flexDirection="column"
        alignItems="stretch"
        padding={1}
        height="fit"
      >
        {/* Title */}
        <Section
          flexDirection="column"
          alignItems="start"
          gap={0.25}
          width="full"
        >
          <Icon size={24} />
          <Text headingH3 text04>
            {title}
          </Text>
        </Section>

        {/* Pricing */}
        <Section
          flexDirection="row"
          justifyContent="start"
          alignItems="center"
          gap={0.5}
          height="auto"
        >
          {pricing && (
            <Text headingH2 text04>
              {pricing}
            </Text>
          )}
          <Text
            secondaryBody
            text03
            className={
              pricing ? "whitespace-pre-line" : "whitespace-pre-line min-h-9"
            }
          >
            {description}
          </Text>
        </Section>

        {/* Button */}
        <div className="plan-card-button">
          {isCurrentPlan ? (
            // TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved
            <Button tertiary transient className="pointer-events-none">
              <Text mainUiAction text03>
                {t("currentPlan")}
              </Text>
            </Button>
          ) : href ? (
            <OpalButton
              prominence="secondary"
              href={href}
              target="_blank"
              rel="noopener noreferrer"
            >
              {buttonLabel}
            </OpalButton>
          ) : onClick ? (
            <OpalButton onClick={onClick} icon={ButtonIcon}>
              {buttonLabel}
            </OpalButton>
          ) : (
            // TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved
            <Button tertiary transient className="pointer-events-none">
              <Text mainUiAction text03>
                {t("includedInPlan")}
              </Text>
            </Button>
          )}
        </div>
      </Section>

      {/* Features */}
      <div
        className="plan-card-features-container"
        data-hidden={hideFeatures ? "true" : "false"}
      >
        <Section
          flexDirection="column"
          alignItems="start"
          justifyContent="start"
          gap={1}
          padding={1}
        >
          <Text mainUiBody text03>
            {featuresPrefix}
          </Text>
          <Section
            flexDirection="column"
            alignItems="start"
            gap={0.5}
            height="auto"
          >
            {features.map((feature) => (
              <Section
                key={feature.textKey}
                flexDirection="row"
                alignItems="start"
                justifyContent="start"
                gap={0.25}
                width="fit"
                height="auto"
              >
                <div className="plan-card-feature-icon">
                  <feature.icon size={16} className="stroke-text-03" />
                </div>
                <Text mainUiBody text03>
                  {t(`features.${feature.textKey}`)}
                </Text>
              </Section>
            ))}
          </Section>
        </Section>
      </div>
    </Card>
  );
}

// ----------------------------------------------------------------------------
// PlansView
// ----------------------------------------------------------------------------

interface PlansViewProps {
  hasSubscription?: boolean;
  hasLicense?: boolean;
  onCheckout: () => void;
  hideFeatures?: boolean;
}

export default function PlansView({
  hasSubscription,
  hasLicense,
  onCheckout,
  hideFeatures,
}: PlansViewProps) {
  const t = useTranslations("admin.billing");

  const plans: PlanConfig[] = [
    {
      icon: SvgUsers,
      title: t("business.title"),
      pricing: t("business.pricing"),
      description: t("business.description"),
      buttonLabel: t("business.buttonLabel"),
      buttonVariant: "primary",
      onClick: hasLicense ? undefined : onCheckout,
      features: BUSINESS_FEATURES,
      featuresPrefix: t("business.featuresPrefix"),
      isCurrentPlan: !!hasSubscription,
    },
    {
      icon: SvgOrganization,
      title: t("enterprise.title"),
      description: t("enterprise.description"),
      buttonLabel: t("enterprise.buttonLabel"),
      buttonVariant: "secondary",
      href: SALES_URL,
      features: ENTERPRISE_FEATURES,
      featuresPrefix: t("enterprise.featuresPrefix"),
      isCurrentPlan: !!hasLicense && !hasSubscription,
    },
  ];

  return (
    <Section flexDirection="row" alignItems="stretch" width="full">
      {plans.map((plan) => (
        <PlanCard key={plan.title} {...plan} hideFeatures={hideFeatures} />
      ))}
    </Section>
  );
}
