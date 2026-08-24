import { SvgArrowUpRight, SvgFilterPlus, SvgUserSync } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Button, Card } from "@opal/components";
import { Hoverable } from "@opal/core";
import { clickOnKeyDown } from "@opal/utils";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import Link from "next/link";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useAuthTypeMetadata } from "@/lib/auth/hooks";
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
  const display = value === null ? "\u2014" : value.toLocaleString();

  const cellClassName = `relative flex flex-col items-start gap-0.5 w-full p-2 rounded-08 transition-colors ${
    onFilter ? "cursor-pointer hover:bg-background-tint-02" : ""
  }`;

  const cellBody = (
    <>
      <Text as="span" mainUiAction text04>
        {display}
      </Text>
      <Text as="span" secondaryBody text03>
        {label}
      </Text>
      {onFilter && (
        <div className="absolute right-1 top-1">
          <Hoverable.Item group="stat" variant="appear-on-hover">
            <Button
              prominence="tertiary"
              icon={SvgFilterPlus}
              tooltip="Add Filter"
              tooltipSide="left"
              onClick={(e) => {
                e.stopPropagation();
                onFilter();
              }}
            />
          </Hoverable.Item>
        </div>
      )}
    </>
  );

  return (
    <Hoverable.Root group="stat" width="full">
      {onFilter ? (
        // The cell holds its own filter button, so it stays a div with button
        // semantics rather than a <button> wrapping a <button>.
        <div
          className={cellClassName}
          role="button"
          tabIndex={0}
          aria-label={`Filter by ${label}`}
          onKeyDown={clickOnKeyDown(onFilter)}
          onClick={onFilter}
        >
          {cellBody}
        </div>
      ) : (
        <div className={cellClassName}>{cellBody}</div>
      )}
    </Hoverable.Root>
  );
}

// ---------------------------------------------------------------------------
// SCIM card
// ---------------------------------------------------------------------------

function ScimCard() {
  return (
    <Card border="solid" padding={3} rounding="lg">
      <Section alignItems="start" height="fit" gap={2}>
        <ContentAction
          icon={SvgUserSync}
          title="SCIM Sync"
          description="Users are synced from your identity provider."
          sizePreset="main-ui"
          variant="section"
          padding={0}
          rightChildren={
            <Link href={ADMIN_ROUTES.SCIM.path}>
              <Button
                prominence="tertiary"
                rightIcon={SvgArrowUpRight}
                size="sm"
              >
                Manage
              </Button>
            </Link>
          }
        />
      </Section>
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
  const { authTypeMetadata } = useAuthTypeMetadata();
  const showInviteOnly = !showScim && authTypeMetadata?.multiTenant === false;
  const showRequests = requests !== null && requests > 0;

  const statsCard = (
    <Card border="solid" padding={2} rounding="lg">
      <Section alignItems="start" height="fit">
        <Section flexDirection="row" gap={0}>
          <StatCell
            value={activeUsers}
            label="active users"
            onFilter={onFilterActive}
          />
          <StatCell
            value={pendingInvites}
            label="pending invites"
            onFilter={onFilterInvites}
          />
          {showRequests && (
            <StatCell
              value={requests}
              label="requests to join"
              onFilter={onFilterRequests}
            />
          )}
        </Section>
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
        gap={2}
      >
        {statsCard}
        {rightCard}
      </Section>
    );
  }

  return statsCard;
}
