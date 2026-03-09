import { SvgArrowUpRight, SvgFilter, SvgUserSync } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Button } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import Link from "next/link";
import { ADMIN_PATHS } from "@/lib/admin-routes";

// ---------------------------------------------------------------------------
// Stats cell — number + label, filter icon on hover
// ---------------------------------------------------------------------------

interface StatCellProps {
  value: number | null;
  label: string;
  onClick?: () => void;
}

function StatCell({ value, label, onClick }: StatCellProps) {
  const display = value === null ? "—" : value.toLocaleString();

  return (
    <button
      type="button"
      onClick={onClick}
      className="group relative flex flex-col items-start gap-0.5 w-full p-2 text-left rounded-md hover:bg-background-neutral-02 transition-colors cursor-pointer"
    >
      <Text as="span" mainUiAction text04>
        {display}
      </Text>
      <Text as="span" secondaryBody text03>
        {label}
      </Text>
      <div className="absolute right-2 top-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <Text as="span" secondaryBody text03>
          Filter
        </Text>
        <SvgFilter size={16} className="text-text-03" />
      </div>
    </button>
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

export type StatFilter = "active" | "invited" | "requests";

interface UsersSummaryProps {
  activeUsers: number | null;
  pendingInvites: number | null;
  requests: number | null;
  showScim: boolean;
  onStatClick?: (filter: StatFilter) => void;
}

export default function UsersSummary({
  activeUsers,
  pendingInvites,
  requests,
  showScim,
  onStatClick,
}: UsersSummaryProps) {
  const showRequests = requests !== null && requests > 0;

  const statsCard = (
    <Card padding={0.5}>
      <Section flexDirection="row" gap={0}>
        <StatCell
          value={activeUsers}
          label="active users"
          onClick={() => onStatClick?.("active")}
        />
        <StatCell
          value={pendingInvites}
          label="pending invites"
          onClick={() => onStatClick?.("invited")}
        />
        {showRequests && (
          <StatCell
            value={requests}
            label="requests to join"
            onClick={() => onStatClick?.("requests")}
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

  return statsCard;
}
