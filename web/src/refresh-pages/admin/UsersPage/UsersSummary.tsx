import { SvgArrowUpRight, SvgFilterPlus, SvgUserSync } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import { Hoverable } from "@opal/core";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useAuthTypeMetadata } from "@/hooks/useAuthTypeMetadata";
import { AuthType } from "@/lib/constants";
import InviteOnlyCard from "./InviteOnlyCard";

// ---------------------------------------------------------------------------
// Stats cell — number + label + hover filter icon
// ---------------------------------------------------------------------------

type StatCellProps = {
  value: number | null;
  label: string;
  onFilter?: () => void;
};

function StatCell({ value, label, onFilter }: StatCellProps) {
  const { t } = useTranslation();
  const display = value === null ? "\u2014" : value.toLocaleString();

  return (
    <Hoverable.Root group="stat" width="full">
      <div
        className={`relative flex flex-col items-start gap-0.5 w-full p-2 rounded-08 transition-colors ${
          onFilter ? "cursor-pointer hover:bg-background-tint-02" : ""
        }`}
        onClick={onFilter}
      >
        <Text as="span" mainUiAction text04>
          {display}
        </Text>
        <Text as="span" secondaryBody text03>
          {label}
        </Text>
        {onFilter && (
          <div className="absolute right-1 top-1">
            <Hoverable.Item group="stat" variant="appear-on-hover">
              <IconButton
                tertiary
                icon={SvgFilterPlus}
                tooltip={t("admin.common.add_filter")}
                toolTipPosition="left"
                onClick={(e) => {
                  e.stopPropagation();
                  onFilter();
                }}
              />
            </Hoverable.Item>
          </div>
        )}
      </div>
    </Hoverable.Root>
  );
}

// ---------------------------------------------------------------------------
// SCIM card
// ---------------------------------------------------------------------------

function ScimCard() {
  const { t } = useTranslation();

  return (
    <Card gap={0.5} padding={0.75}>
      <ContentAction
        icon={SvgUserSync}
        title={t("admin.users.scim_sync")}
        description={t("admin.users.scim_sync_desc")}
        sizePreset="main-ui"
        variant="section"
        padding="fit"
        rightChildren={
          <Link href={ADMIN_ROUTES.SCIM.path}>
            <Button prominence="tertiary" rightIcon={SvgArrowUpRight} size="sm">
              {t("admin.common.manage")}
            </Button>
          </Link>
        }
      />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Stats bar — layout varies by SCIM / invite-only status
// ---------------------------------------------------------------------------

type UsersSummaryProps = {
  activeUsers: number | null;
  pendingInvites: number | null;
  requests: number | null;
  showScim: boolean;
  onFilterActive?: () => void;
  onFilterInvites?: () => void;
  onFilterRequests?: () => void;
};

export default function UsersSummary({
  activeUsers,
  pendingInvites,
  requests,
  showScim,
  onFilterActive,
  onFilterInvites,
  onFilterRequests,
}: UsersSummaryProps) {
  const { t } = useTranslation();
  const { authTypeMetadata } = useAuthTypeMetadata();
  const showInviteOnly =
    !showScim &&
    (authTypeMetadata.authType === AuthType.BASIC ||
      authTypeMetadata.authType === AuthType.GOOGLE_OAUTH);
  const showRequests = requests !== null && requests > 0;

  const statsCard = (
    <Card padding={0.5}>
      <Section flexDirection="row" gap={0}>
        <StatCell
          value={activeUsers}
          label={t("admin.users.active_users")}
          onFilter={onFilterActive}
        />
        <StatCell
          value={pendingInvites}
          label={t("admin.users.pending_invites")}
          onFilter={onFilterInvites}
        />
        {showRequests && (
          <StatCell
            value={requests}
            label={t("admin.users.requests_to_join")}
            onFilter={onFilterRequests}
          />
        )}
      </Section>
    </Card>
  );

  const rightCard = showScim ? (
    <ScimCard />
  ) : showInviteOnly ? (
    <InviteOnlyCard />
  ) : null;

  if (rightCard) {
    return (
      <Section
        flexDirection="row"
        justifyContent="start"
        alignItems="stretch"
        gap={0.5}
      >
        {statsCard}
        {rightCard}
      </Section>
    );
  }

  return statsCard;
}
