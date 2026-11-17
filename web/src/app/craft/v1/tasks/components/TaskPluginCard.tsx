"use client";

import { useTranslations } from "next-intl";
import { Button, Card, InputSwitch, SelectCard, Text } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgPlug, SvgSettings } from "@opal/icons";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";
import type {
  TaskActionSettings,
  TaskActionView,
  TaskLinkValue,
  TaskPluginView,
} from "@/app/craft/v1/tasks/types";
import type { PolicyValue } from "@/lib/integrations/types";

function runPolicy(value: TaskLinkValue, action: TaskActionView): PolicyValue {
  if (value === "blocked" || action.integration_policy === "blocked")
    return "blocked";
  if (value === "inherit" || (value === "allow" && action.locked))
    return action.integration_policy;
  return value;
}

interface TaskPluginCardProps {
  plugin: TaskPluginView;
  enabled: boolean;
  settings: TaskActionSettings;
  onEdit: () => void;
  onToggle: (enabled: boolean) => void;
}

export default function TaskPluginCard({
  plugin,
  enabled,
  settings,
  onEdit,
  onToggle,
}: TaskPluginCardProps) {
  const t = useTranslations("craft.actionPolicies");
  const counts: Record<PolicyValue, number> = {
    allow: 0,
    ask: 0,
    blocked: 0,
  };
  for (const integration of plugin.integrations) {
    for (const action of integration.actions) {
      counts[
        runPolicy(settings.actions[action.key] ?? settings.default, action)
      ]++;
    }
  }
  const signInProblem = plugin.integrations.find(
    (integration) => integration.status.state !== "connected"
  );
  const appType = plugin.integrations.find(
    (integration) => integration.app_type !== null
  )?.app_type;
  const PluginIcon = appType ? getAppTypeLogo(appType) : SvgPlug;
  return (
    <SelectCard
      state={enabled ? "filled" : "empty"}
      onClick={onEdit}
      padding={0}
      border="solid"
      rounding={4}
      role="group"
      aria-label={plugin.plugin_name}
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
              <PluginIcon size={24} className="text-text-03" />
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
                  title={plugin.plugin_name}
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
                    app: plugin.plugin_name,
                  })}
                  onCheckedChange={onToggle}
                />
              </Section>
            </Section>
            <Text font="secondary-body" color="text-03">
              {plugin.integrations
                .map((integration) => integration.name)
                .join(", ")}
            </Text>
            {signInProblem && (
              <Text font="secondary-body" color="status-warning-05">
                {signInProblem.status.reason ??
                  t("needsSignIn", { name: signInProblem.name })}
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
