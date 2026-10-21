"use client";

import { useTranslations } from "next-intl";
import { Button, Card, InputSwitch, SelectCard, Text } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgPlug, SvgSettings } from "@opal/icons";
import {
  getAppTypeLogo,
  type ActionPolicy,
} from "@/app/craft/v1/apps/registry";
import type { AppActionPoliciesView } from "@/lib/plugins/types";
import type { MemberPluginConnection } from "@/lib/plugins/member";

interface TaskPluginCardProps {
  app: AppActionPoliciesView;
  enabled: boolean;
  policies: Record<string, ActionPolicy>;
  connection: MemberPluginConnection | undefined;
  onConnect: () => void;
  onEdit: () => void;
  onToggle: (enabled: boolean) => void;
}

export default function TaskPluginCard({
  app,
  enabled,
  policies,
  connection,
  onConnect,
  onEdit,
  onToggle,
}: TaskPluginCardProps) {
  const t = useTranslations("craft.actionPolicies");
  const tConnection = useTranslations("actions.memberPlugins.row");
  const tStatus = useTranslations("actions.memberPlugins.status");
  const connectionKnown = connection !== undefined;
  const needsConnection = connectionKnown && connection.kind !== "connected";
  const unavailable = !connectionKnown && !enabled;
  const counts = { auto: 0, ask: 0, disabled: 0 };
  for (const action of app.actions) {
    const policy = action.editable
      ? (policies[action.action_id] ?? action.effective_policy)
      : action.effective_policy;
    if (policy === "ALWAYS") counts.auto++;
    else if (policy === "ASK") counts.ask++;
    else counts.disabled++;
  }
  const PluginIcon = app.app_type ? getAppTypeLogo(app.app_type) : SvgPlug;
  return (
    <SelectCard
      state={
        enabled && connectionKnown && !needsConnection ? "filled" : "empty"
      }
      disabled={unavailable}
      onClick={() => {
        if (needsConnection) onConnect();
        else onEdit();
      }}
      padding={0}
      border="solid"
      rounding={4}
      role="group"
      aria-label={app.name}
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
            gap={3}
            className="min-w-0 flex-1"
          >
            <Section height="auto" alignItems="stretch" gap={1}>
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
                  <Content sizePreset="main-content" title={app.name} />
                  {needsConnection && (
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
                    disabled={unavailable || needsConnection}
                    aria-label={t("manageActions")}
                    tooltip={
                      unavailable
                        ? tStatus("unavailable")
                        : needsConnection
                          ? tConnection("connect", { name: app.name })
                          : t("manageActions")
                    }
                    onClick={onEdit}
                  />
                  {needsConnection && (
                    <Button
                      icon={SvgPlug}
                      size="sm"
                      prominence="secondary"
                      aria-label={tConnection("connect", {
                        name: app.name,
                      })}
                      tooltip={tConnection("connect", {
                        name: app.name,
                      })}
                      onClick={onConnect}
                    />
                  )}
                  {(!needsConnection || enabled) && (
                    <InputSwitch
                      checked={enabled}
                      disabled={unavailable}
                      aria-label={t("enableAppForTask", {
                        app: app.name,
                      })}
                      onCheckedChange={onToggle}
                    />
                  )}
                </Section>
              </Section>
              <Text font="secondary-body" color="text-03">
                {t(app.kind === "external_app" ? "externalApp" : "mcpServer")}
              </Text>
            </Section>
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
            {enabled ? t("policyCounts", counts) : t("disabledForTask")}
          </Text>
        </Section>
      </Section>
    </SelectCard>
  );
}
