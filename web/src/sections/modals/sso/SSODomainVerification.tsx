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

function RecordRow({
  label,
  value,
  copyable,
}: {
  label: string;
  value: string;
  copyable?: boolean;
}) {
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

function DomainCard({
  status,
  busy,
  onVerify,
}: {
  status: SSOLoginDomainStatus;
  busy: boolean;
  onVerify: () => void;
}) {
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
                disabled={busy}
                icon={busy ? SvgSimpleLoader : undefined}
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
// DNS TXT record. Records populate before the provider is saved, so setup is one pass.
export default function SSODomainVerification({
  domains,
}: SSODomainVerificationProps) {
  const { data, mutate, isLoading } = useSWR<SSOLoginDomains>(
    domains.length > 0 ? SWR_KEYS.adminSsoDomainRecords(domains) : null,
    () => fetchDomainRecords(domains)
  );
  const [busyDomain, setBusyDomain] = useState<string | null>(null);

  if (domains.length === 0) return null;

  async function verify(domain: string) {
    setBusyDomain(domain);
    try {
      await verifyDomainViaDns(domain);
      await mutate();
      toast.success(`${domain} verified`);
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
