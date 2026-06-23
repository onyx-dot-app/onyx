"use client";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
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
// Plan Features
// ----------------------------------------------------------------------------

const BUSINESS_FEATURES: PlanFeature[] = [
  { icon: SvgFiles, text: "Inherit Document Permissions" },
  { icon: SvgHistory, text: "Query History and Usage Dashboard" },
  { icon: SvgShield, text: "Role Based Access Control (RBAC)" },
  { icon: SvgLock, text: "Encryption of Secrets" },
  { icon: SvgKey, text: "Service Account API Keys" },
  { icon: SvgHardDrive, text: "Self-hosting (Optional)" },
  { icon: SvgPaintBrush, text: "Custom Theming" },
];

const ENTERPRISE_FEATURES: PlanFeature[] = [
  { icon: SvgUsers, text: "SCIM / Group Sync" },
  { icon: SvgDashboard, text: "Full White-labeling" },
  { icon: SvgUserManage, text: "Custom Roles and Permissions" },
  { icon: SvgSliders, text: "Configurable Usage Limits" },
  { icon: SvgShareWebhook, text: "Hook Extensions" },
  { icon: SvgServer, text: "Custom Deployments" },
  { icon: SvgGlobe, text: "Region-Specific Data Processing" },
  { icon: SvgHeadsetMic, text: "Enterprise SLAs and Priority Support" },
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
  const { t } = useTranslation();
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
                {t("admin.billing.your_current_plan")}
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
                {t("admin.billing.included_in_your_plan")}
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
                key={feature.text}
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
  const { t } = useTranslation();

  const businessFeatures = useMemo<PlanFeature[]>(() => [
    { icon: SvgFiles, text: t("admin.billing.feature_inherit_document_permissions") },
    { icon: SvgHistory, text: t("admin.billing.feature_query_history_usage") },
    { icon: SvgShield, text: t("admin.billing.feature_rbac") },
    { icon: SvgLock, text: t("admin.billing.feature_encryption_secrets") },
    { icon: SvgKey, text: t("admin.billing.feature_service_account_keys") },
    { icon: SvgHardDrive, text: t("admin.billing.feature_self_hosting") },
    { icon: SvgPaintBrush, text: t("admin.billing.feature_custom_theming") },
  ], [t]);

  const enterpriseFeatures = useMemo<PlanFeature[]>(() => [
    { icon: SvgUsers, text: t("admin.billing.feature_scim_sync") },
    { icon: SvgDashboard, text: t("admin.billing.feature_white_labeling") },
    { icon: SvgUserManage, text: t("admin.billing.feature_custom_roles_permissions") },
    { icon: SvgSliders, text: t("admin.billing.feature_configurable_usage_limits") },
    { icon: SvgShareWebhook, text: t("admin.billing.feature_hook_extensions") },
    { icon: SvgServer, text: t("admin.billing.feature_custom_deployments") },
    { icon: SvgGlobe, text: t("admin.billing.feature_region_data_processing") },
    { icon: SvgHeadsetMic, text: t("admin.billing.feature_enterprise_support") },
  ], [t]);

  const plans: PlanConfig[] = [
    {
      icon: SvgUsers,
      title: t("admin.billing.plan_business"),
      pricing: "$20",
      description: t("admin.billing.business_pricing_desc"),
      buttonLabel: t("admin.billing.get_business_plan"),
      buttonVariant: "primary",
      onClick: hasLicense ? undefined : onCheckout,
      features: businessFeatures,
      featuresPrefix: t("admin.billing.business_features_prefix"),
      isCurrentPlan: !!hasSubscription,
    },
    {
      icon: SvgOrganization,
      title: t("admin.billing.plan_enterprise"),
      description: t("admin.billing.enterprise_pricing_desc"),
      buttonLabel: t("admin.billing.contact_sales"),
      buttonVariant: "secondary",
      href: SALES_URL,
      features: enterpriseFeatures,
      featuresPrefix: t("admin.billing.enterprise_features_prefix"),
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
