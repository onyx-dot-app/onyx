import { SvgArrowUpRight, SvgUserSync } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Separator from "@/refresh-components/Separator";
import Text from "@/refresh-components/texts/Text";
import Link from "next/link";
import { ADMIN_PATHS } from "@/lib/admin-routes";

// ---------------------------------------------------------------------------
// Stats cell
// ---------------------------------------------------------------------------

interface StatCellProps {
  value: number | null;
  label: string;
}

function StatCell({ value, label }: StatCellProps) {
  const display = value === null ? "—" : value.toLocaleString();

  return (
    <Section alignItems="start" gap={0.25} width="fit" padding={0.5}>
      <Text as="p" headingH3 text05>
        {display}
      </Text>
      <Text as="p" mainUiMuted text03>
        {label}
      </Text>
    </Section>
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

interface StatsBarProps {
  activeUsers: number | null;
  pendingInvites: number | null;
  requests: number | null;
  showScim: boolean;
}

export default function StatsBar({
  activeUsers,
  pendingInvites,
  requests,
  showScim,
}: StatsBarProps) {
  if (showScim) {
    // With SCIM: one card containing all 3 stats (dividers) + separate SCIM card
    return (
      <Section
        flexDirection="row"
        justifyContent="start"
        alignItems="stretch"
        gap={0.5}
      >
        <Card padding={0}>
          <Section
            flexDirection="row"
            alignItems="stretch"
            gap={0}
            width="fit"
            height="auto"
          >
            <StatCell value={activeUsers} label="active users" />
            <Separator orientation="vertical" noPadding />
            <StatCell value={pendingInvites} label="pending invites" />
            {requests !== null && (
              <>
                <Separator orientation="vertical" noPadding />
                <StatCell value={requests} label="requests to join" />
              </>
            )}
          </Section>
        </Card>

        <ScimCard />
      </Section>
    );
  }

  // Without SCIM: 3 separate cards
  return (
    <Section
      flexDirection="row"
      justifyContent="start"
      alignItems="stretch"
      gap={0.5}
    >
      <Card padding={0.5}>
        <StatCell value={activeUsers} label="active users" />
      </Card>
      <Card padding={0.5}>
        <StatCell value={pendingInvites} label="pending invites" />
      </Card>
      {requests !== null && (
        <Card padding={0.5}>
          <StatCell value={requests} label="requests to join" />
        </Card>
      )}
    </Section>
  );
}
