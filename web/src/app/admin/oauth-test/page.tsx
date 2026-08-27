"use client";

import { useTranslations } from "next-intl";
import { PageLoader } from "@opal/layouts";
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
  const t = useTranslations("admin.oauthTest");
  const entries = Object.entries(claims);
  return (
    <div className="flex flex-col gap-2">
      <Text font="heading-h3">{title}</Text>
      <Text font="main-ui-body" color="text-03">
        {subtitle}
      </Text>
      {entries.length === 0 ? (
        <Text font="main-ui-body" color="text-03">
          {t("claims.empty.message")}
        </Text>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-64">
                {t("claims.table.claim.header")}
              </TableHead>
              <TableHead>{t("claims.table.value.header")}</TableHead>
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
  const t = useTranslations("admin.oauthTest");
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
        errorTitle={t("loadFailed.title")}
        errorMsg={error?.info?.detail || String(error)}
      />
    );
  }

  return (
    <div className="flex flex-col gap-6 pb-8">
      <div className="flex flex-col gap-2">
        <Text font="main-ui-body" color="text-03">
          {t("intro.description")}
        </Text>
        <div>
          <Button onClick={() => (window.location.href = RERUN_URL)}>
            {t("rerun.label")}
          </Button>
        </div>
      </div>

      {!snapshot.found ? (
        <ErrorCallout
          errorTitle={t("noSnapshot.title")}
          errorMsg={t("noSnapshot.description", { email: snapshot.email })}
        />
      ) : (
        <>
          <div className="flex flex-col gap-1">
            <Text font="main-ui-body" color="text-03">
              {t("snapshot.user.label", { email: snapshot.email })}
            </Text>
            <Text font="main-ui-body" color="text-03">
              {t("snapshot.provider.label", {
                provider: snapshot.oauth_name ?? "-",
              })}
            </Text>
            <Text font="main-ui-body" color="text-03">
              {t("snapshot.capturedAt.label", {
                timestamp: snapshot.captured_at ?? "-",
              })}
            </Text>
            <Text font="main-ui-body" color="text-03">
              {t("snapshot.tokenFields.label", {
                fields: formatClaimValue(snapshot.token_meta?.keys ?? []),
              })}
            </Text>
          </div>

          <ClaimsTable
            title={t("idToken.title")}
            subtitle={t("idToken.subtitle")}
            claims={snapshot.id_token_claims ?? {}}
          />
          <ClaimsTable
            title={t("userinfo.title")}
            subtitle={t("userinfo.subtitle")}
            claims={snapshot.userinfo ?? {}}
          />
          {snapshot.directory_profile && (
            <ClaimsTable
              title={t("directory.title", {
                source:
                  snapshot.directory_source ?? t("directory.fallbackSource"),
              })}
              subtitle={t("directory.subtitle")}
              claims={snapshot.directory_profile}
            />
          )}
          {snapshot.resolved_profile &&
            Object.keys(snapshot.resolved_profile).length > 0 && (
              <ClaimsTable
                title={t("resolved.title")}
                subtitle={t("resolved.subtitle", {
                  placeholder: "{{user.*}}",
                })}
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
