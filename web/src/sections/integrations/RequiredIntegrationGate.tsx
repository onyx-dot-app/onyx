"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import * as Dialog from "@radix-ui/react-dialog";
import { Button, Card, Divider, Text } from "@opal/components";
import {
  AuthLayouts,
  Content,
  ContentIndent,
  Section,
  toast,
} from "@opal/layouts";
import { SvgCheckCircle, SvgLogOut, SvgPlug } from "@opal/icons";
import { useNavigation, usePathname, useSearchParams } from "@opal/navigation";
import { loginPath } from "@/lib/auth/paths";
import { Logo } from "@/lib/app/components/Logo";
import { LOGOUT_DISABLED } from "@/lib/constants";
import { requiredSignIns } from "@/lib/integrations/connect";
import { useMemberIntegrations } from "@/lib/integrations/hooks";
import type { MemberIntegration } from "@/lib/integrations/types";
import { isOAuthCallbackPath } from "@/lib/oauth/desktopCallback";
import { checkUserIsNoAuthUser, logout } from "@/lib/users/svc";
import { useUser } from "@/providers/UserProvider";
import IntegrationConnectButton from "@/sections/plugins/IntegrationConnectButton";

const LOGO_SIZE_PX = 44;
const DISMISSED_KEY = "onyx:required-gate-dismissed";

function readDismissed(userId: string): boolean {
  try {
    return window.sessionStorage.getItem(DISMISSED_KEY) === userId;
  } catch {
    return false;
  }
}

function storeDismissed(userId: string): void {
  try {
    window.sessionStorage.setItem(DISMISSED_KEY, userId);
  } catch {}
}

export default function RequiredIntegrationGate() {
  const { user } = useUser();
  const pathname = usePathname();
  if (!user || user.is_anonymous_user || checkUserIsNoAuthUser(user.id))
    return null;
  // The OAuth callback must finish while the gate waits for it.
  if (isOAuthCallbackPath(pathname)) return null;
  return <GateForUser userId={user.id} />;
}

function GateForUser({ userId }: { userId: string }) {
  const { isAdmin } = useUser();
  // A failed read shows no gate until data arrives; a failed refresh keeps
  // the last data.
  const { data } = useMemberIntegrations();
  const [trackedIds, setTrackedIds] = useState<number[]>([]);
  const [dismissed, setDismissed] = useState(() => readDismissed(userId));

  const blockingIds = useMemo(
    () =>
      data === undefined
        ? []
        : requiredSignIns(data).map((integration) => integration.id),
    [data]
  );

  useEffect(() => {
    setTrackedIds((current) => {
      const added = blockingIds.filter((id) => !current.includes(id));
      return added.length === 0 ? current : [...current, ...added];
    });
  }, [blockingIds]);

  const rows = useMemo(() => {
    const ids = [
      ...trackedIds,
      ...blockingIds.filter((id) => !trackedIds.includes(id)),
    ];
    const byId = new Map((data ?? []).map((item) => [item.id, item]));
    return ids.flatMap((id) => {
      const integration = byId.get(id);
      return integration &&
        (blockingIds.includes(id) || integration.status.state === "connected")
        ? [integration]
        : [];
    });
  }, [trackedIds, blockingIds, data]);

  if (dismissed || rows.length === 0) return null;

  function dismiss() {
    storeDismissed(userId);
    setDismissed(true);
  }

  return (
    <RequiredIntegrationGateView
      integrations={rows}
      canContinue={isAdmin || blockingIds.length === 0}
      isAdmin={isAdmin}
      onContinue={() => {
        if (isAdmin) dismiss();
        else setTrackedIds([]);
      }}
      onSkip={dismiss}
    />
  );
}

interface RequiredIntegrationGateViewProps {
  integrations: MemberIntegration[];
  canContinue: boolean;
  isAdmin: boolean;
  onContinue: () => void;
  onSkip: () => void;
}

function RequiredIntegrationGateView({
  integrations,
  canContinue,
  isAdmin,
  onContinue,
  onSkip,
}: RequiredIntegrationGateViewProps) {
  const t = useTranslations("integrations.requiredGate");
  const navigation = useNavigation();
  const pathname = usePathname();
  const query = useSearchParams().toString();
  const returnPath = query ? `${pathname}?${query}` : pathname;
  const containerRef = useRef<HTMLDivElement>(null);
  const [failedName, setFailedName] = useState<string | null>(null);
  const connectedCount = integrations.filter(
    (integration) => integration.status.state === "connected"
  ).length;

  // A connected row loses its Connect button, so move focus to the next one.
  useEffect(() => {
    const active = document.activeElement;
    if (active && active !== document.body) return;
    containerRef.current
      ?.querySelector<HTMLButtonElement>("button:not([disabled])")
      ?.focus();
  }, [connectedCount]);

  async function signOut() {
    try {
      const response = await logout();
      if (!response.ok) {
        toast.error(t("signOutFailed"));
        return;
      }
      navigation.go(loginPath({ next: returnPath, autoRedirectToSso: false }));
    } catch {
      toast.error(t("signOutFailed"));
    }
  }

  return (
    <Dialog.Root open modal>
      <Dialog.Portal>
        <Dialog.Content
          aria-describedby={undefined}
          onEscapeKeyDown={(event) => event.preventDefault()}
          onPointerDownOutside={(event) => event.preventDefault()}
          onInteractOutside={(event) => event.preventDefault()}
          ref={containerRef}
          className="fixed inset-0 z-(--z-modal-overlay) overflow-y-auto bg-background focus:outline-hidden"
        >
          <AuthLayouts.Root>
            <Section height="fit" gap={6} padding={4} className="max-w-[34rem]">
              <Section height="fit" gap={3}>
                <Logo size={LOGO_SIZE_PX} />
                <Dialog.Title asChild>
                  <div>
                    <Text
                      as="h1"
                      font="heading-headline"
                      color="text-05"
                      textPosition="text-center"
                    >
                      {t("title")}
                    </Text>
                  </div>
                </Dialog.Title>
                <Text
                  as="p"
                  font="main-ui-body"
                  color="text-03"
                  textPosition="text-center"
                >
                  {isAdmin ? t("adminDescription") : t("description")}
                </Text>
              </Section>
              <Card padding={2} border="solid">
                <Section height="fit" gap={0} alignItems="stretch">
                  {integrations.map((integration, index) => (
                    <Section key={integration.id} height="fit" gap={0}>
                      {index > 0 && <Divider paddingParallel={2} />}
                      <GateRow
                        integration={integration}
                        returnPath={returnPath}
                        onConnectFailed={() => setFailedName(integration.name)}
                      />
                    </Section>
                  ))}
                </Section>
              </Card>
              <Section height="fit" gap={2} alignItems="stretch">
                <Text
                  as="p"
                  font="secondary-body"
                  color="text-03"
                  textPosition="text-center"
                >
                  {t("progress", {
                    connected: connectedCount,
                    total: integrations.length,
                  })}
                </Text>
                <Button
                  width="full"
                  disabled={!canContinue}
                  onClick={onContinue}
                >
                  {t("continue")}
                </Button>
                {failedName !== null && !canContinue && (
                  <>
                    <Text
                      as="p"
                      font="secondary-body"
                      color="text-03"
                      textPosition="text-center"
                    >
                      {t("askAdmin", { name: failedName })}
                    </Text>
                    <Button
                      width="full"
                      prominence="secondary"
                      onClick={onSkip}
                    >
                      {t("skip")}
                    </Button>
                  </>
                )}
                {!LOGOUT_DISABLED && (
                  <Button
                    width="full"
                    prominence="tertiary"
                    icon={SvgLogOut}
                    onClick={() => void signOut()}
                  >
                    {t("signOut")}
                  </Button>
                )}
              </Section>
            </Section>
          </AuthLayouts.Root>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

interface GateRowProps {
  integration: MemberIntegration;
  returnPath: string;
  onConnectFailed: () => void;
}

function GateRow({ integration, returnPath, onConnectFailed }: GateRowProps) {
  const t = useTranslations("integrations.requiredGate");
  const connected = integration.status.state === "connected";
  const note = connected
    ? t("connected")
    : integration.status.state === "needs_reconnect"
      ? integration.status.reason
      : null;
  return (
    <Section
      role="group"
      aria-label={integration.name}
      flexDirection="row"
      justifyContent="between"
      alignItems="center"
      height="fit"
      gap={3}
      padding={2}
    >
      <Section height="fit" gap={0.5} alignItems="start" grow={1}>
        <Content
          font="main-content-emphasis"
          icon={connected ? SvgCheckCircle : SvgPlug}
          color={connected ? "success" : "default"}
          title={integration.name}
          description={integration.description ?? undefined}
        />
        {note && (
          <ContentIndent font="main-content-emphasis">
            <Text
              as="p"
              font="secondary-body"
              color={connected ? "status-success-05" : "text-03"}
            >
              {note}
            </Text>
          </ContentIndent>
        )}
      </Section>
      {!connected && (
        <Section width="fit" height="fit" shrink={false}>
          <IntegrationConnectButton
            integration={integration}
            returnPath={returnPath}
            onConnectFailed={onConnectFailed}
          />
        </Section>
      )}
    </Section>
  );
}
