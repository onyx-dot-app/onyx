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
import { useTranslations } from "next-intl";
import "@/app/admin/billing/billing.css";
import type { IconProps } from "@opal/types";
import Card from "@/refresh-components/cards/Card";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";

const SALES_URL = "https://www.onyx.app/contact-sales";

// ----------------------------------------------------------------------------
// Types
// ----------------------------------------------------------------------------

interface PlanFeature {
  icon: React.FunctionComponent<IconProps>;
  text: string;
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
      aria-label={t("plans.card.ariaLabel", { plan: title })}
      className="plan-card"
    >
      <Section
        flexDirection="column"
        alignItems="stretch"
        padding={4}
        height="fit"
      >
        {/* Title */}
        <Section flexDirection="column" alignItems="start" gap={1} width="full">
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
          gap={2}
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
            // Not a button: it states which plan you are on. It only ever
            // wore a button so it would fill the same slot, which `w-full` and
            // the shared 2.25rem box now do directly.
            <div className="w-full flex items-center justify-center rounded-12 p-2 bg-background-tint-00">
              <Text mainUiAction text03>
                {t("plans.currentPlan.label")}
              </Text>
            </div>
          ) : href ? (
            <Button
              prominence="secondary"
              href={href}
              target="_blank"
              rel="noopener noreferrer"
            >
              {buttonLabel}
            </Button>
          ) : onClick ? (
            <Button onClick={onClick} icon={ButtonIcon}>
              {buttonLabel}
            </Button>
          ) : (
            // Not a button: it states which plan you are on. It only ever
            // wore a button so it would fill the same slot, which `w-full` and
            // the shared 2.25rem box now do directly.
            <div className="w-full flex items-center justify-center rounded-12 p-2 bg-background-tint-00">
              <Text mainUiAction text03>
                {t("plans.includedInPlan.label")}
              </Text>
            </div>
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
          gap={4}
          padding={4}
        >
          <Text mainUiBody text03>
            {featuresPrefix}
          </Text>
          <Section
            flexDirection="column"
            alignItems="start"
            gap={2}
            height="auto"
          >
            {features.map((feature) => (
              <Section
                key={feature.text}
                flexDirection="row"
                alignItems="start"
                justifyContent="start"
                gap={1}
                width="fit"
                height="auto"
              >
                <div className="plan-card-feature-icon">
                  <feature.icon size={16} className="stroke-text-03" />
                </div>
                <Text mainUiBody text03>
                  {feature.text}
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

  const businessFeatures: PlanFeature[] = [
    { icon: SvgFiles, text: t("plans.business.features.documentPermissions") },
    { icon: SvgHistory, text: t("plans.business.features.queryHistory") },
    { icon: SvgShield, text: t("plans.business.features.rbac") },
    { icon: SvgLock, text: t("plans.business.features.encryption") },
    { icon: SvgKey, text: t("plans.business.features.apiKeys") },
    { icon: SvgHardDrive, text: t("plans.business.features.selfHosting") },
    { icon: SvgPaintBrush, text: t("plans.business.features.theming") },
  ];

  const enterpriseFeatures: PlanFeature[] = [
    { icon: SvgUsers, text: t("plans.enterprise.features.scim") },
    { icon: SvgDashboard, text: t("plans.enterprise.features.whiteLabeling") },
    { icon: SvgUserManage, text: t("plans.enterprise.features.customRoles") },
    { icon: SvgSliders, text: t("plans.enterprise.features.usageLimits") },
    {
      icon: SvgShareWebhook,
      text: t("plans.enterprise.features.hookExtensions"),
    },
    {
      icon: SvgServer,
      text: t("plans.enterprise.features.customDeployments"),
    },
    {
      icon: SvgGlobe,
      text: t("plans.enterprise.features.regionalProcessing"),
    },
    { icon: SvgHeadsetMic, text: t("plans.enterprise.features.support") },
  ];

  const plans: PlanConfig[] = [
    {
      icon: SvgUsers,
      title: t("plans.business.title"),
      pricing: t("plans.business.pricing"),
      description: t("plans.business.description"),
      buttonLabel: t("plans.business.button.label"),
      buttonVariant: "primary",
      onClick: hasLicense ? undefined : onCheckout,
      features: businessFeatures,
      featuresPrefix: t("plans.business.featuresPrefix"),
      isCurrentPlan: !!hasSubscription,
    },
    {
      icon: SvgOrganization,
      title: t("plans.enterprise.title"),
      description: t("plans.enterprise.description"),
      buttonLabel: t("plans.enterprise.button.label"),
      buttonVariant: "secondary",
      href: SALES_URL,
      features: enterpriseFeatures,
      featuresPrefix: t("plans.enterprise.featuresPrefix"),
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
