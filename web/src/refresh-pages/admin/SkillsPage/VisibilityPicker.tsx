"use client";

import { Card, SelectCard, Tag } from "@opal/components";
import { SvgGlobe, SvgLock, SvgUser, SvgUsers } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";
import type { SkillVisibility } from "@/refresh-pages/admin/SkillsPage/interfaces";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface VisibilityPickerProps {
  visibility: SkillVisibility;
  onChange: (visibility: SkillVisibility) => void;
  /** When false, the org-wide option is locked behind a "Request" affordance. */
  canSetOrgWide: boolean;
}

interface VisibilityOption {
  value: SkillVisibility;
  label: string;
  description: string;
  icon: typeof SvgLock;
}

const OPTIONS: VisibilityOption[] = [
  {
    value: "private",
    label: "Private",
    description: "Only you have access.",
    icon: SvgLock,
  },
  {
    value: "users",
    label: "Specific users",
    description: "Pick individual users in the org.",
    icon: SvgUser,
  },
  {
    value: "groups",
    label: "Groups",
    description: "Pick one or more groups (your groups for non-admins).",
    icon: SvgUsers,
  },
  {
    value: "users_and_groups",
    label: "Users + groups",
    description: "Combine specific users and groups.",
    icon: SvgUsers,
  },
  {
    value: "org_wide",
    label: "Org-wide",
    description: "Everyone in the org has access.",
    icon: SvgGlobe,
  },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function VisibilityPicker({
  visibility,
  onChange,
  canSetOrgWide,
}: VisibilityPickerProps) {
  return (
    <Section gap={0.5} alignItems="stretch">
      {OPTIONS.map((option) => {
        const isOrgWideLocked = option.value === "org_wide" && !canSetOrgWide;
        const isSelected = visibility === option.value;

        return (
          <SelectCard
            key={option.value}
            state={isSelected ? "selected" : "empty"}
            disabled={isOrgWideLocked}
            onClick={() => {
              if (isOrgWideLocked) return;
              onChange(option.value);
            }}
          >
            <ContentAction
              sizePreset="main-ui"
              variant="section"
              icon={option.icon}
              title={option.label}
              description={option.description}
              rightChildren={
                isOrgWideLocked ? (
                  <Tag title="Admin only" color="amber" />
                ) : isSelected ? (
                  <Tag title="Selected" color="blue" />
                ) : undefined
              }
            />
          </SelectCard>
        );
      })}

      {!canSetOrgWide && (
        <Card padding="md">
          <Section gap={0.5} alignItems="start">
            <Text as="span" mainUiAction text05>
              Need org-wide reach?
            </Text>
            <Text as="span" mainUiBody text03>
              Use the <strong>Request org-wide</strong> action on the
              skill&apos;s detail page after upload. An admin sees the request
              on /admin/skills and can promote your skill from there.
            </Text>
          </Section>
        </Card>
      )}
    </Section>
  );
}
