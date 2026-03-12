"use client";

import type { UserGroup } from "@/lib/types";
import { SvgChevronRight, SvgUserManage, SvgUsers } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";
import { buildGroupDescription, formatMemberCount } from "./utils";

interface GroupCardProps {
  group: UserGroup;
}

function GroupCard({ group }: GroupCardProps) {
  const isBasic = group.name === "Basic";
  const isAdmin = group.name === "Admin";

  return (
    <Card padding={0.5}>
      <ContentAction
        icon={isAdmin ? SvgUserManage : SvgUsers}
        title={group.name}
        description={buildGroupDescription(group)}
        sizePreset="main-content"
        variant="section"
        tag={isBasic ? { title: "Default" } : undefined}
        rightChildren={
          <Section flexDirection="row" alignItems="center">
            <Text mainUiBody text03>
              {formatMemberCount(group.users.length)}
            </Text>
            <IconButton icon={SvgChevronRight} tertiary tooltip="View group" />
          </Section>
        }
      />
    </Card>
  );
}

export default GroupCard;
