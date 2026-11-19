"use client";

import { useTranslations } from "next-intl";
import { Button, Card, InputSwitch, SelectCard, Text } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgPlug, SvgSettings } from "@opal/icons";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";
import type {
  TaskActionSettings,
  TaskActionView,
  TaskIntegrationView,
} from "@/app/craft/v1/tasks/types";
import type { LinkValue, PolicyValue } from "@/lib/integrations/types";

function runPolicy(value: LinkValue, action: TaskActionView): PolicyValue {
  if (value === "blocked" || action.integration_policy === "blocked")
    return "blocked";
  if (value === "inherit" || (value === "allow" && action.locked))
    return action.integration_policy;
  return value;
}

interface TaskIntegrationCardProps {
  integration: TaskIntegrationView;
  enabled: boolean;
  settings: TaskActionSettings;
  onEdit: () => void;
  onToggle: (enabled: boolean) => void;
}

export default function TaskIntegrationCard({
  integration,
  enabled,
  settings,
  onEdit,
  onToggle,
}: TaskIntegrationCardProps) {
  const t = useTranslations("craft.actionPolicies");
  const counts: Record<PolicyValue, number> = {
    allow: 0,
    ask: 0,
    blocked: 0,
  };
  for (const action of integration.actions) {
    counts[
      runPolicy(settings.actions[action.key] ?? settings.default, action)
    ]++;
  }
  const signInProblem = integration.status.state !== "connected";
  const IntegrationIcon = integration.app_type
    ? getAppTypeLogo(integration.app_type)
    : SvgPlug;
  return (
    <SelectCard
      state={enabled ? "filled" : "empty"}
      onClick={onEdit}
      padding={0}
      border="solid"
      rounding={4}
      role="group"
      aria-label={integration.name}
    >
      <Section height="full" alignItems="stretch" gap={0}>
        <Section
          height="auto"
          padding={4}
          flexDirection="row"
          alignItems="start"
          gap={3}
        >
          <Section width="fit" height="auto" className="shrink-0">
            <Card padding={2} border="solid" rounding={3}>
              <IntegrationIcon size={24} className="text-text-03" />
            </Card>
          </Section>
          <Section
            height="auto"
            alignItems="stretch"
            gap={1}
            className="min-w-0 flex-1"
          >
            <Section
              height="auto"
              flexDirection="row"
              justifyContent="between"
              gap={3}
            >
              <Section
                width="fit"
                height="auto"
                flexDirection="row"
                gap={2}
                className="min-w-0"
              >
                <Content
                  font="main-content-emphasis"
                  title={integration.name}
                />
                {signInProblem && (
                  <span
                    aria-hidden
                    className="size-2 shrink-0 rounded-full bg-status-warning-05"
                  />
                )}
              </Section>
              <Section
                width="fit"
                height="auto"
                flexDirection="row"
                gap={2}
                className="shrink-0"
                onClick={(event) => event.stopPropagation()}
              >
                <Button
                  icon={SvgSettings}
                  size="sm"
                  prominence="tertiary"
                  aria-label={t("manageActions")}
                  tooltip={t("manageActions")}
                  onClick={onEdit}
                />
                <InputSwitch
                  checked={enabled}
                  aria-label={t("enableAppForTask", {
                    app: integration.name,
                  })}
                  onCheckedChange={onToggle}
                />
              </Section>
            </Section>
            {signInProblem && (
              <Text font="secondary-body" color="status-warning-05">
                {integration.status.reason ??
                  t("needsSignIn", { name: integration.name })}
              </Text>
            )}
            {!integration.runnable && (
              <Text font="secondary-body" color="status-warning-05">
                {t("notRunnable", { name: integration.name })}
              </Text>
            )}
          </Section>
        </Section>
        <Section
          height="auto"
          padding={3}
          alignItems="start"
          gap={1}
          className="mt-auto"
        >
          <Text font="secondary-body" color="text-03">
            {enabled ? t("taskPolicyCounts", counts) : t("disabledForTask")}
          </Text>
        </Section>
      </Section>
    </SelectCard>
  );
}
