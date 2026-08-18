"use client";

import { useId, useState } from "react";
import useSWR from "swr";
import { Button, Card, CopyButton, Tag, Text } from "@opal/components";
import { Hoverable } from "@opal/core";
import { InputVertical, Section, toast } from "@opal/layouts";
import { SvgSimpleLoader } from "@opal/icons";
import {
  fetchDomainRecords,
  verifyDomainViaDns,
  type SSOLoginDomains,
  type SSOLoginDomainStatus,
} from "@/lib/sso/svc";
import { SWR_KEYS } from "@/lib/swr-keys";

interface SSODomainVerificationProps {
  domains: string[];
}

// Both stay plain text: the label is interpolated into a "label: " prefix, and
// the value is copied verbatim into the reader's DNS record.
interface RecordRowProps {
  label: string;
  value: string;
  copyable?: boolean;
}

function RecordRow({ label, value, copyable }: RecordRowProps) {
  const group = useId();
  const row = (
    <Section
      flexDirection="row"
      alignItems="center"
      justifyContent="between"
      height="fit"
      gap={2}
      padding={2}
      className={
        copyable ? "transition-colors hover:bg-background-tint-02" : undefined
      }
    >
      <div className="min-w-0 break-all">
        <Text font="main-ui-body" color="text-03" as="span">
          {`${label}: `}
        </Text>
        <Text font="main-ui-mono" color="text-04" as="span">
          {value}
        </Text>
      </div>
      {copyable && (
        <Hoverable.Item group={group} variant="appear-on-hover">
          <CopyButton getCopyText={() => value} size="sm" />
        </Hoverable.Item>
      )}
    </Section>
  );

  return copyable ? <Hoverable.Root group={group}>{row}</Hoverable.Root> : row;
}

interface DomainCardProps {
  status: SSOLoginDomainStatus;
  busy: boolean;
  onVerify: () => void;
}

function DomainCard({ status, busy, onVerify }: DomainCardProps) {
  return (
    <Card border="solid" rounding="lg">
      <Section flexDirection="column" alignItems="stretch" height="fit" gap={3}>
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          height="fit"
          gap={2}
        >
          <Text font="main-ui-action" color="text-05" as="span">
            {status.domain}
          </Text>
          <Tag
            color={status.verified ? "green" : "amber"}
            title={status.verified ? "Verified" : "Pending"}
          />
        </Section>

        {status.verified ? (
          <Text font="secondary-body" color="text-03" as="span">
            This domain signs its users in automatically.
          </Text>
        ) : (
          <>
            <Text font="secondary-body" color="text-03" as="span">
              Add this TXT record at your DNS provider, then verify.
            </Text>
            <Card border="solid" rounding="md" padding={0}>
              <Section
                flexDirection="column"
                alignItems="stretch"
                height="fit"
                gap={0}
                className="[&>*+*]:border-t [&>*+*]:border-border-01"
              >
                <RecordRow label="Type" value="TXT" />
                {status.record_host && (
                  <RecordRow label="Name" value={status.record_host} copyable />
                )}
                {status.record_value && (
                  <RecordRow
                    label="Value"
                    value={status.record_value}
                    copyable
                  />
                )}
              </Section>
            </Card>
            <Section flexDirection="row" justifyContent="end" height="fit">
              <Button
                prominence="secondary"
                onClick={onVerify}
                disabled={busy || !status.claimed}
                icon={busy ? SvgSimpleLoader : undefined}
                tooltip={
                  status.claimed
                    ? undefined
                    : "Save the provider with this domain first."
                }
              >
                Verify domain
              </Button>
            </Section>
          </>
        )}
      </Section>
    </Card>
  );
}

// Cloud only: a domain routes no one until the workspace proves ownership with a
// DNS TXT record. The record shows for an unsaved domain so it can be published
// early, but verifying it needs the saved claim the backend checks against.
export default function SSODomainVerification({
  domains,
}: SSODomainVerificationProps) {
  const { data, mutate, isLoading, error } = useSWR<SSOLoginDomains>(
    domains.length > 0 ? SWR_KEYS.adminSsoDomainRecords(domains) : null,
    () => fetchDomainRecords(domains)
  );
  const [busyDomain, setBusyDomain] = useState<string | null>(null);

  if (domains.length === 0) return null;

  async function verify(domain: string) {
    setBusyDomain(domain);
    try {
      await verifyDomainViaDns(domain);
      toast.success(`${domain} verified`);
      // The backend persisted it, so apply the result locally before asking for
      // a refresh. A failed refresh then cannot report success as a failure or
      // leave the row sitting on its old pending state.
      await mutate(
        (current) =>
          current && {
            domains: current.domains.map((row) =>
              row.domain === domain
                ? {
                    ...row,
                    verified: true,
                    claimed: true,
                    record_host: null,
                    record_value: null,
                  }
                : row
            ),
          },
        { revalidate: true, rollbackOnError: false }
      ).catch(() => undefined);
    } catch (exc) {
      toast.error(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusyDomain(null);
    }
  }

  const rows = data?.domains ?? [];

  return (
    <InputVertical
      title="Domain verification"
      description="A domain signs your workspace's users in automatically only after you verify you own it. Add the DNS record below, then verify."
      withLabel
    >
      <Section flexDirection="column" alignItems="stretch" height="fit" gap={3}>
        {/* Sits above the rows rather than replacing them: a failed refresh
            keeps the last rows, and showing them as current would hide that
            their verified state is no longer known. */}
        {error && (
          <Card border="solid" rounding="lg">
            <Section
              flexDirection="row"
              alignItems="center"
              justifyContent="between"
              height="fit"
              gap={2}
            >
              <Text font="main-ui-body" color="text-03" as="span">
                {rows.length > 0
                  ? "We couldn't refresh these records, so they may be out of date."
                  : "We couldn't load the DNS records."}
              </Text>
              <Button prominence="secondary" onClick={() => void mutate()}>
                Try again
              </Button>
            </Section>
          </Card>
        )}
        {isLoading && rows.length === 0 ? (
          <Section flexDirection="row" alignItems="center" height="fit" gap={2}>
            <SvgSimpleLoader className="text-text-03" />
            <Text font="main-ui-body" color="text-03">
              Loading…
            </Text>
          </Section>
        ) : (
          rows.map((status) => (
            <DomainCard
              key={status.domain}
              status={status}
              busy={busyDomain === status.domain}
              onVerify={() => verify(status.domain)}
            />
          ))
        )}
      </Section>
    </InputVertical>
  );
}
