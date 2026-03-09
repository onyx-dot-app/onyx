import { SvgArrowUpRight, SvgFilter, SvgUserSync } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import Link from "next/link";
import { ADMIN_PATHS } from "@/lib/admin-routes";

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

  return (
    <div
      className={`group/stat relative flex flex-col items-start gap-0.5 w-full p-2 rounded-08 transition-colors ${
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
        <div className="absolute right-2 top-2 flex items-center gap-1 opacity-0 group-hover/stat:opacity-100 transition-opacity">
          <Text as="span" secondaryBody text03>
            Filter
          </Text>
          <SvgFilter size={16} className="text-text-03" />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SCIM card
// ---------------------------------------------------------------------------

function ScimCard() {
  return (
    <Card gap={0.5} padding={0.75}>
      <ContentAction
        icon={SvgUserSync}
        title="SCIM Sync"
        description="Users are synced from your identity provider."
        sizePreset="main-ui"
        variant="section"
        paddingVariant="fit"
        rightChildren={
          <Link href={ADMIN_PATHS.SCIM}>
            <Button prominence="tertiary" rightIcon={SvgArrowUpRight} size="sm">
              Manage
            </Button>
          </Link>
        }
      />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Stats bar — layout varies by SCIM status
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
  const showRequests = requests !== null && requests > 0;

  const statsCard = (
    <Card padding={0.5}>
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
    </Card>
  );

  if (showScim) {
    return (
      <Section
        flexDirection="row"
        justifyContent="start"
        alignItems="stretch"
        gap={0.5}
      >
        {statsCard}
        <ScimCard />
      </Section>
    );
  }

  // No SCIM — each stat gets its own card
  return (
    <Section flexDirection="row" gap={0.5}>
      <Card padding={0.5}>
        <StatCell
          value={activeUsers}
          label="active users"
          onFilter={onFilterActive}
        />
      </Card>
      <Card padding={0.5}>
        <StatCell
          value={pendingInvites}
          label="pending invites"
          onFilter={onFilterInvites}
        />
      </Card>
      {showRequests && (
        <Card padding={0.5}>
          <StatCell
            value={requests}
            label="requests to join"
            onFilter={onFilterRequests}
          />
        </Card>
      )}
    </Section>
  );
}
