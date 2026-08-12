"use client";

import SimpleTabs from "@/refresh-components/SimpleTabs";
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

const GLOBAL_DESCRIPTION =
  "Global limits apply to all users, user groups, and API keys. When the global limit is reached, no more tokens can be spent.";
const USER_DESCRIPTION =
  "User limits apply to each user individually. When a user reaches a limit, they are temporarily blocked from spending tokens.";
const USER_GROUP_DESCRIPTION =
  "Group limits apply to all users in a group. If a user belongs to multiple groups, the most permissive limit applies.";
const CREATE_ERROR_MESSAGE = "Failed to create spending limit";

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
      toast.success("Spending limit created!");
      updateTable(targetScope);
    } catch (error) {
      console.error("Failed to create spending limit:", error);
      toast.error(
        error instanceof Error ? error.message : CREATE_ERROR_MESSAGE
      );
    }
  }

  return (
    <Section alignItems="stretch" justifyContent="start" height="auto">
      {embedded ? (
        <Section gap={1} alignItems="start" justifyContent="start">
          <Text font="heading-h3">Manage spending limits</Text>
          <Text font="secondary-body" color="text-03">
            Set guardrails for workspace, user, and group usage. Limits can be
            enabled or disabled without deleting their configuration.
          </Text>
        </Section>
      ) : (
        <>
          <Text as="p">
            Spending limits help you control how many tokens can be spent in a
            given time period.
          </Text>
          <ul className="list-disc ml-4">
            <li>
              <Text as="p">
                Set a workspace-wide limit for your team&apos;s overall spend.
              </Text>
            </li>
            {enterpriseTier && (
              <>
                <li>
                  <Text as="p">
                    Set limits for users so no single user can spend too much.
                  </Text>
                </li>
                <li>
                  <Text as="p">
                    Set limits for user groups to control spend for teams.
                  </Text>
                </li>
              </>
            )}
            <li>
              <Text as="p">Enable and disable limits as needed.</Text>
            </li>
          </ul>
        </>
      )}

      <Button
        icon={SvgPlusCircle}
        prominence="secondary"
        onClick={() => setModalIsOpen(true)}
      >
        Create spending limit
      </Button>

      {enterpriseTier ? (
        <SimpleTabs
          tabs={{
            "0": {
              name: "Global",
              icon: SvgGlobe,
              content: (
                <GenericTokenRateLimitTable
                  fetchUrl={GLOBAL_TOKEN_FETCH_URL}
                  description={GLOBAL_DESCRIPTION}
                />
              ),
            },
            "1": {
              name: "Users",
              icon: SvgUser,
              content: (
                <GenericTokenRateLimitTable
                  fetchUrl={USER_TOKEN_FETCH_URL}
                  description={USER_DESCRIPTION}
                />
              ),
            },
            "2": {
              name: "Groups",
              icon: SvgUsers,
              content: (
                <GenericTokenRateLimitTable
                  fetchUrl={USER_GROUP_FETCH_URL}
                  description={USER_GROUP_DESCRIPTION}
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
          description={GLOBAL_DESCRIPTION}
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
