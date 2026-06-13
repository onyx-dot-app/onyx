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

const SALES_URL = "https://glomi.ai/contact-sales";

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
  { icon: SvgFiles, text: "继承文档权限" },
  { icon: SvgHistory, text: "查询历史与使用情况仪表板" },
  { icon: SvgShield, text: "基于角色的访问控制（RBAC）" },
  { icon: SvgLock, text: "密钥加密" },
  { icon: SvgKey, text: "服务账号 API Key" },
  { icon: SvgHardDrive, text: "自托管（可选）" },
  { icon: SvgPaintBrush, text: "自定义主题" },
];

const ENTERPRISE_FEATURES: PlanFeature[] = [
  { icon: SvgUsers, text: "SCIM / 用户组同步" },
  { icon: SvgDashboard, text: "完整白标" },
  { icon: SvgUserManage, text: "自定义角色和权限" },
  { icon: SvgSliders, text: "可配置使用限制" },
  { icon: SvgShareWebhook, text: "Hook 扩展" },
  { icon: SvgServer, text: "自定义部署" },
  { icon: SvgGlobe, text: "按区域处理数据" },
  { icon: SvgHeadsetMic, text: "企业 SLA 和优先支持" },
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
                当前套餐
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
                已包含在你的套餐中
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
  const plans: PlanConfig[] = [
    {
      icon: SvgUsers,
      title: "Business",
      pricing: "$20",
      description:
        "每席/月，按年计费\n或按月计费每席 $25",
      buttonLabel: "获取 Business 套餐",
      buttonVariant: "primary",
      onClick: hasLicense ? undefined : onCheckout,
      features: BUSINESS_FEATURES,
      featuresPrefix: "用 AI 帮你的团队完成更多工作。",
      isCurrentPlan: !!hasSubscription,
    },
    {
      icon: SvgOrganization,
      title: "Enterprise",
      description:
        "面向大型组织的灵活定价和部署选项",
      buttonLabel: "联系销售",
      buttonVariant: "secondary",
      href: SALES_URL,
      features: ENTERPRISE_FEATURES,
      featuresPrefix: "包含 Business 套餐全部能力，另加：",
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
