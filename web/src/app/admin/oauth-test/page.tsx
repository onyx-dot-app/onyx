"use client";

import { PageLoader } from "@/refresh-components/PageLoader";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SettingsLayouts } from "@opal/layouts";
import { ErrorCallout } from "@/components/ErrorCallout";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Table,
} from "@/components/ui/table";
import { Button, Text } from "@opal/components";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.OAUTH_TEST;

// Runs the normal OIDC login flow and lands back on this page — the backend
// re-captures the claims on every login.
const RERUN_URL =
  "/api/auth/oidc/authorize?next=/admin/oauth-test&redirect=true";

// --- Types ---

interface OAuthClaimsSnapshot {
  found: boolean;
  email: string;
  captured_at: string | null;
  oauth_name: string | null;
  id_token_claims: Record<string, unknown> | null;
  userinfo: Record<string, unknown> | null;
  directory_profile: Record<string, unknown> | null;
  directory_source: string | null;
  resolved_profile: Record<string, string> | null;
  enrichment_enabled: boolean;
  token_meta: Record<string, unknown> | null;
}

// --- Components ---

function formatClaimValue(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function ClaimsTable({
  title,
  subtitle,
  claims,
}: {
  title: string;
  subtitle: string;
  claims: Record<string, unknown>;
}) {
  const entries = Object.entries(claims);
  return (
    <div className="flex flex-col gap-2">
      <Text font="heading-h3">{title}</Text>
      <Text font="main-ui-body" color="text-03">
        {subtitle}
      </Text>
      {entries.length === 0 ? (
        <Text font="main-ui-body" color="text-03">
          No claims received.
        </Text>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-64">Claim</TableHead>
              <TableHead>Value</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map(([key, value]) => (
              <TableRow key={key}>
                <TableCell className="font-mono text-xs align-top">
                  {key}
                </TableCell>
                <TableCell className="font-mono text-xs whitespace-pre-wrap break-all">
                  {formatClaimValue(value)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

function Main() {
  const {
    data: snapshot,
    error,
    isLoading,
  } = useSWR<OAuthClaimsSnapshot>(
    SWR_KEYS.adminOAuthTestClaims,
    errorHandlingFetcher
  );

  if (isLoading) {
    return <PageLoader />;
  }

  if (error || !snapshot) {
    return (
      <ErrorCallout
        errorTitle="Failed to load OAuth claims"
        errorMsg={error?.info?.detail || String(error)}
      />
    );
  }

  return (
    <div className="flex flex-col gap-6 pb-8">
      <div className="flex flex-col gap-2">
        <Text font="main-ui-body" color="text-03">
          Shows the raw fields your identity provider sent about you during your
          last OAuth/OIDC login: the id_token claims and the userinfo endpoint
          response. Use it to verify which attributes the IdP is configured to
          release. Claims are captured at every login.
        </Text>
        <div>
          <Button onClick={() => (window.location.href = RERUN_URL)}>
            Re-run OAuth login
          </Button>
        </div>
      </div>

      {!snapshot.found ? (
        <ErrorCallout
          errorTitle="No captured claims yet"
          errorMsg={`No OAuth login snapshot found for ${snapshot.email}. Log in through the identity provider (button above) and reload this page.`}
        />
      ) : (
        <>
          <div className="flex flex-col gap-1">
            <Text font="main-ui-body" color="text-03">
              {`User: ${snapshot.email}`}
            </Text>
            <Text font="main-ui-body" color="text-03">
              {`Provider: ${snapshot.oauth_name ?? "-"}`}
            </Text>
            <Text font="main-ui-body" color="text-03">
              {`Captured at: ${snapshot.captured_at ?? "-"}`}
            </Text>
            <Text font="main-ui-body" color="text-03">
              {`Token response fields: ${formatClaimValue(
                snapshot.token_meta?.keys ?? []
              )}`}
            </Text>
          </div>

          <ClaimsTable
            title="id_token claims"
            subtitle="Decoded from the id_token JWT returned by the token endpoint."
            claims={snapshot.id_token_claims ?? {}}
          />
          <ClaimsTable
            title="userinfo claims"
            subtitle="Response of the OIDC userinfo endpoint for your access token."
            claims={snapshot.userinfo ?? {}}
          />
          {snapshot.directory_profile && (
            <ClaimsTable
              title={`Directory profile (${snapshot.directory_source ?? "provider API"})`}
              subtitle="Directory fields fetched from the provider API — e.g. Microsoft Graph /me for Entra ID, which carries country/usageLocation that the id_token omits unless the ctry optional claim is configured."
              claims={snapshot.directory_profile}
            />
          )}
          {snapshot.resolved_profile &&
            Object.keys(snapshot.resolved_profile).length > 0 && (
              <ClaimsTable
                title="Resolved profile (used for prompts)"
                subtitle="The claim-mapped directory profile that actually feeds the Organization Profile prompt block and {{user.*}} placeholders."
                claims={snapshot.resolved_profile}
              />
            )}
        </>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} divider />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
