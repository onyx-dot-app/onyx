"use client";

import SimpleTabs from "@/refresh-components/SimpleTabs";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { toast } from "@opal/layouts";
import { useState } from "react";
import { mutate } from "swr";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Section } from "@/layouts/general-layouts";
import { SvgGlobe, SvgPlusCircle, SvgUser, SvgUsers } from "@opal/icons";
import {
  insertGlobalTokenRateLimit,
  insertGroupTokenRateLimit,
  insertUserTokenRateLimit,
} from "./lib";
import { Scope, TokenRateLimit } from "./types";
import { GenericTokenRateLimitTable } from "./TokenRateLimitTables";
import CreateRateLimitModal from "./CreateRateLimitModal";

const GLOBAL_TOKEN_FETCH_URL = SWR_KEYS.globalTokenRateLimits;
const USER_TOKEN_FETCH_URL = SWR_KEYS.userTokenRateLimits;
const USER_GROUP_FETCH_URL = SWR_KEYS.userGroupTokenRateLimits;

async function createTokenRateLimit(
  targetScope: Scope,
  periodHours: number,
  tokenBudget: number | null,
  costBudgetCents: number | null,
  groupId: number
): Promise<void> {
  const tokenRateLimitArgs = {
    enabled: true,
    token_budget: tokenBudget,
    period_hours: periodHours,
    cost_budget_cents: costBudgetCents,
  };

  if (targetScope === Scope.GLOBAL) {
    await insertGlobalTokenRateLimit(tokenRateLimitArgs);
  } else if (targetScope === Scope.USER) {
    await insertUserTokenRateLimit(tokenRateLimitArgs);
  } else if (targetScope === Scope.USER_GROUP) {
    await insertGroupTokenRateLimit(tokenRateLimitArgs, groupId);
  } else {
    throw new Error(`Invalid target scope: ${targetScope}`);
  }
}

interface TokenRateLimitsPanelProps {
  embedded?: boolean;
}

export default function TokenRateLimitsPanel({
  embedded = false,
}: TokenRateLimitsPanelProps) {
  const t = useTranslations("admin.tokenRateLimits");
  const [tabIndex, setTabIndex] = useState(0);
  const [modalIsOpen, setModalIsOpen] = useState(false);
  const enterpriseTier = useTierAtLeast(Tier.ENTERPRISE);

  function updateTable(targetScope: Scope) {
    if (targetScope === Scope.GLOBAL) {
      mutate(GLOBAL_TOKEN_FETCH_URL);
      setTabIndex(0);
    } else if (targetScope === Scope.USER) {
      mutate(USER_TOKEN_FETCH_URL);
      setTabIndex(1);
    } else if (targetScope === Scope.USER_GROUP) {
      mutate(USER_GROUP_FETCH_URL);
      setTabIndex(2);
    }
  }

  async function handleSubmit(
    targetScope: Scope,
    periodHours: number,
    tokenBudget: number | null,
    costBudgetCents: number | null,
    groupId: number = -1
  ): Promise<void> {
    try {
      await createTokenRateLimit(
        targetScope,
        periodHours,
        tokenBudget,
        costBudgetCents,
        groupId
      );
      setModalIsOpen(false);
      toast.success(t("panel.created.message"));
      updateTable(targetScope);
    } catch (error) {
      console.error("Failed to create spending limit:", error);
      toast.error(
        error instanceof Error ? error.message : t("panel.createFailed.error")
      );
    }
  }

  return (
    <Section alignItems="stretch" justifyContent="start" height="auto">
      {embedded ? (
        <Section gap={1} alignItems="start" justifyContent="start">
          <Text font="heading-h3">{t("panel.embedded.title")}</Text>
          <Text font="secondary-body" color="text-03">
            {t("panel.embedded.description")}
          </Text>
        </Section>
      ) : (
        <>
          <Text as="p">{t("panel.intro.description")}</Text>
          <ul className="list-disc ml-4">
            <li>
              <Text as="p">{t("panel.intro.workspaceLimit")}</Text>
            </li>
            {enterpriseTier && (
              <>
                <li>
                  <Text as="p">{t("panel.intro.userLimit")}</Text>
                </li>
                <li>
                  <Text as="p">{t("panel.intro.groupLimit")}</Text>
                </li>
              </>
            )}
            <li>
              <Text as="p">{t("panel.intro.toggleLimit")}</Text>
            </li>
          </ul>
        </>
      )}

      <Button
        icon={SvgPlusCircle}
        prominence="secondary"
        onClick={() => setModalIsOpen(true)}
      >
        {t("panel.create.label")}
      </Button>

      {enterpriseTier ? (
        <SimpleTabs
          tabs={{
            "0": {
              name: t("panel.tabs.global.name"),
              icon: SvgGlobe,
              content: (
                <GenericTokenRateLimitTable
                  fetchUrl={GLOBAL_TOKEN_FETCH_URL}
                  description={t("panel.global.description")}
                />
              ),
            },
            "1": {
              name: t("panel.tabs.users.name"),
              icon: SvgUser,
              content: (
                <GenericTokenRateLimitTable
                  fetchUrl={USER_TOKEN_FETCH_URL}
                  description={t("panel.user.description")}
                />
              ),
            },
            "2": {
              name: t("panel.tabs.groups.name"),
              icon: SvgUsers,
              content: (
                <GenericTokenRateLimitTable
                  fetchUrl={USER_GROUP_FETCH_URL}
                  description={t("panel.userGroup.description")}
                  responseMapper={(data: Record<string, TokenRateLimit[]>) =>
                    Object.entries(data).flatMap(([groupName, elements]) =>
                      elements.map((element) => ({
                        ...element,
                        group_name: groupName,
                      }))
                    )
                  }
                />
              ),
            },
          }}
          value={tabIndex.toString()}
          onValueChange={(value) => setTabIndex(parseInt(value, 10))}
        />
      ) : (
        <GenericTokenRateLimitTable
          fetchUrl={GLOBAL_TOKEN_FETCH_URL}
          description={t("panel.global.description")}
        />
      )}

      <CreateRateLimitModal
        isOpen={modalIsOpen}
        setIsOpen={() => setModalIsOpen(false)}
        onSubmit={handleSubmit}
        forSpecificScope={enterpriseTier ? undefined : Scope.GLOBAL}
      />
    </Section>
  );
}
