import { SvgArrowUpRight, SvgUserSync } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import Link from "next/link";
import { ADMIN_PATHS } from "@/lib/admin-routes";

// ---------------------------------------------------------------------------
// Stats cell — number + label
// ---------------------------------------------------------------------------

type StatCellProps = {
  value: number | null;
  label: string;
};

function StatCell({ value, label }: StatCellProps) {
  const display = value === null ? "\u2014" : value.toLocaleString();

  return (
    <div className="flex flex-col items-start gap-0.5 w-full p-2">
      <Text as="span" mainUiAction text04>
        {display}
      </Text>
      <Text as="span" secondaryBody text03>
        {label}
      </Text>
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
};

export default function UsersSummary({
  activeUsers,
  pendingInvites,
  requests,
  showScim,
}: UsersSummaryProps) {
  const showRequests = requests !== null && requests > 0;

  if (showScim) {
    return (
      <Section
        flexDirection="row"
        justifyContent="start"
        alignItems="stretch"
        gap={0.5}
      >
        <Card padding={0.5}>
          <Section flexDirection="row" gap={0}>
            <StatCell value={activeUsers} label="active users" />
            <StatCell value={pendingInvites} label="pending invites" />
            {showRequests && (
              <StatCell value={requests} label="requests to join" />
            )}
          </Section>
        </Card>
        <ScimCard />
      </Section>
    );
  }

  // No SCIM — each stat gets its own card
  return (
    <Section flexDirection="row" gap={0.5}>
      <Card padding={0.5}>
        <StatCell value={activeUsers} label="active users" />
      </Card>
      <Card padding={0.5}>
        <StatCell value={pendingInvites} label="pending invites" />
      </Card>
      {showRequests && (
        <Card padding={0.5}>
          <StatCell value={requests} label="requests to join" />
        </Card>
      )}
    </Section>
  );
}
