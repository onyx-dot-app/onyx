"use client";

import type { ReactNode } from "react";
import { Button, Card, Tabs, Text } from "@opal/components";
import { KeyValue, Section, SettingsLayouts } from "@opal/layouts";
import { SvgArrowLeft } from "@opal/icons";
import type { Route } from "next";
import { useNavigation } from "@opal/navigation";
import type { IconFunctionComponent, RichStr } from "@opal/types";

interface BackLinkProps<T extends string> {
  to: Route<T>;
  label: string | RichStr;
}

export function BackLink<T extends string>({ to, label }: BackLinkProps<T>) {
  const navigation = useNavigation();
  return (
    <Button
      prominence="tertiary"
      icon={SvgArrowLeft}
      {...navigation.linkTo(to)}
    >
      {label}
    </Button>
  );
}

export interface DetailTab<T extends string> {
  value: T;
  label: string | RichStr;
  content: ReactNode;
  /** Keep the tab's state, such as unsaved edits, while another tab shows. */
  keepMounted?: boolean;
}

interface CustomizeDetailLayoutProps<T extends string> {
  back: ReactNode;
  icon?: IconFunctionComponent;
  title: string | RichStr;
  description?: string | RichStr;
  tags?: ReactNode;
  actions?: ReactNode[];
  loading: boolean;
  error: string | false;
  /** Null until the item has loaded. */
  tabs: DetailTab<T>[] | null;
  tab: T;
  onTabChange: (tab: T) => void;
  children?: ReactNode;
}

export default function CustomizeDetailLayout<T extends string>({
  back,
  icon,
  title,
  description,
  tags,
  actions,
  loading,
  error,
  tabs,
  tab,
  onTabChange,
  children,
}: CustomizeDetailLayoutProps<T>) {
  // A tab this user cannot see, for example from a shared link, shows the
  // first tab.
  const shown = tabs?.some((candidate) => candidate.value === tab)
    ? tab
    : tabs?.[0]?.value;
  return (
    <SettingsLayouts.Root width="lg" loading={loading} error={error}>
      <SettingsLayouts.Header
        icon={icon}
        title={title}
        description={description}
        back={back}
        actions={actions}
        stackActionsOnMobile
      >
        {tags && (
          <Section
            flexDirection="row"
            justifyContent="start"
            height="auto"
            gap={1}
          >
            {tags}
          </Section>
        )}
      </SettingsLayouts.Header>
      <SettingsLayouts.Body>
        {tabs && (
          <Tabs
            value={shown}
            variant="underline"
            gap={6}
            onValueChange={(value) => {
              const next = tabs.find((candidate) => candidate.value === value);
              if (next) onTabChange(next.value);
            }}
          >
            <Tabs.List>
              {tabs.map((candidate) => (
                <Tabs.Trigger key={candidate.value} value={candidate.value}>
                  {candidate.label}
                </Tabs.Trigger>
              ))}
            </Tabs.List>
            {tabs.map((candidate) => (
              <Tabs.Content
                key={candidate.value}
                value={candidate.value}
                keepMounted={candidate.keepMounted}
              >
                {candidate.content}
              </Tabs.Content>
            ))}
          </Tabs>
        )}
      </SettingsLayouts.Body>
      {children}
    </SettingsLayouts.Root>
  );
}

export interface DetailFact {
  label: string | RichStr;
  value: string | RichStr;
  mono?: boolean;
}

interface DetailOverviewProps {
  descriptionLabel: string | RichStr;
  description: string | RichStr;
  facts: DetailFact[];
  footer?: ReactNode;
}

export function DetailOverview({
  descriptionLabel,
  description,
  facts,
  footer,
}: DetailOverviewProps) {
  return (
    <Section flexDirection="row" alignItems="start" height="auto" gap={6} wrap>
      <Section gap={1} alignItems="stretch" height="auto" grow={3} basis={20}>
        <Text as="p" font="secondary-body" color="text-03">
          {descriptionLabel}
        </Text>
        <Text as="p" font="main-content-body" color="text-04">
          {description}
        </Text>
      </Section>
      <Section height="auto" alignItems="stretch" grow={1} basis={18}>
        <Card padding={4}>
          <Section gap={3} alignItems="stretch" height="auto">
            {facts.map((fact, index) => (
              <KeyValue
                key={index}
                label={fact.label}
                value={fact.value}
                mono={fact.mono}
              />
            ))}
            {footer}
          </Section>
        </Card>
      </Section>
    </Section>
  );
}
