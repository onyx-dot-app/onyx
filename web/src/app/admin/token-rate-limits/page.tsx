"use client";

import SimpleTabs from "@/refresh-components/SimpleTabs";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Button, Text } from "@opal/components";
import { useState } from "react";
import {
  insertGlobalTokenRateLimit,
  insertGroupTokenRateLimit,
  insertUserTokenRateLimit,
} from "./lib";
import { Scope, TokenRateLimit } from "./types";
import { GenericTokenRateLimitTable } from "./TokenRateLimitTables";
import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { toast } from "@/hooks/useToast";
import CreateRateLimitModal from "./CreateRateLimitModal";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { SvgGlobe, SvgPlusCircle, SvgUser, SvgUsers } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.TOKEN_RATE_LIMITS;
const GLOBAL_TOKEN_FETCH_URL = SWR_KEYS.globalTokenRateLimits;
const USER_TOKEN_FETCH_URL = SWR_KEYS.userTokenRateLimits;
const USER_GROUP_FETCH_URL = SWR_KEYS.userGroupTokenRateLimits;

const GLOBAL_DESCRIPTION =
  "Global rate limits apply to all users, user groups, and API keys. When the global \
  rate limit is reached, no more tokens can be spent.";
const USER_DESCRIPTION =
  "User rate limits apply to individual users. When a user reaches a limit, they will \
  be temporarily blocked from spending tokens.";
const USER_GROUP_DESCRIPTION =
  "User group rate limits apply to all users in a group. When a group reaches a limit, \
  all users in the group will be temporarily blocked from spending tokens, regardless \
  of their individual limits. If a user is in multiple groups, the most lenient limit \
  will apply.";

const handleCreateTokenRateLimit = async (
  target_scope: Scope,
  period_hours: number,
  token_budget: number,
  group_id: number = -1
) => {
  const tokenRateLimitArgs = {
    enabled: true,
    token_budget: token_budget,
    period_hours: period_hours,
  };

  if (target_scope === Scope.GLOBAL) {
    return await insertGlobalTokenRateLimit(tokenRateLimitArgs);
  } else if (target_scope === Scope.USER) {
    return await insertUserTokenRateLimit(tokenRateLimitArgs);
  } else if (target_scope === Scope.USER_GROUP) {
    return await insertGroupTokenRateLimit(tokenRateLimitArgs, group_id);
  } else {
    throw new Error(`Invalid target_scope: ${target_scope}`);
  }
};

function Main() {
  const [tabIndex, setTabIndex] = useState(0);
  const [modalIsOpen, setModalIsOpen] = useState(false);

  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  const updateTable = (target_scope: Scope) => {
    if (target_scope === Scope.GLOBAL) {
      mutate(GLOBAL_TOKEN_FETCH_URL);
      setTabIndex(0);
    } else if (target_scope === Scope.USER) {
      mutate(USER_TOKEN_FETCH_URL);
      setTabIndex(1);
    } else if (target_scope === Scope.USER_GROUP) {
      mutate(USER_GROUP_FETCH_URL);
      setTabIndex(2);
    }
  };

  const handleSubmit = (
    target_scope: Scope,
    period_hours: number,
    token_budget: number,
    group_id: number = -1
  ) => {
    handleCreateTokenRateLimit(
      target_scope,
      period_hours,
      token_budget,
      group_id
    )
      .then(() => {
        setModalIsOpen(false);
        toast.success("Token rate limit created!");
        updateTable(target_scope);
      })
      .catch((error) => {
        toast.error(error.message);
      });
  };

  return (
    <Section alignItems="stretch" justifyContent="start" height="auto">
      <Text as="p">
        Token rate limits enable you control how many tokens can be spent in a
        given time period. With token rate limits, you can:
      </Text>

      <ul className="list-disc ml-4">
        <li>
          <Text as="p">
            Set a global rate limit to control your team&apos;s overall token
            spend.
          </Text>
        </li>
        {isPaidEnterpriseFeaturesEnabled && (
          <>
            <li>
              <Text as="p">
                Set rate limits for users to ensure that no single user can
                spend too many tokens.
              </Text>
            </li>
            <li>
              <Text as="p">
                Set rate limits for user groups to control token spend for your
                teams.
              </Text>
            </li>
          </>
        )}
        <li>
          <Text as="p">Enable and disable rate limits on the fly.</Text>
        </li>
      </ul>

      <Button
        icon={SvgPlusCircle}
        prominence="secondary"
        onClick={() => setModalIsOpen(true)}
      >
        Create a Token Rate Limit
      </Button>

      {isPaidEnterpriseFeaturesEnabled ? (
        <SimpleTabs
          tabs={{
            "0": {
              name: "Global",
              icon: SvgGlobe,
              content: (
                <GenericTokenRateLimitTable
                  fetchUrl={GLOBAL_TOKEN_FETCH_URL}
                  title={"Global Token Rate Limits"}
                  description={GLOBAL_DESCRIPTION}
                />
              ),
            },
            "1": {
              name: "User",
              icon: SvgUser,
              content: (
                <GenericTokenRateLimitTable
                  fetchUrl={USER_TOKEN_FETCH_URL}
                  title={"User Token Rate Limits"}
                  description={USER_DESCRIPTION}
                />
              ),
            },
            "2": {
              name: "User Groups",
              icon: SvgUsers,
              content: (
                <GenericTokenRateLimitTable
                  fetchUrl={USER_GROUP_FETCH_URL}
                  title={"User Group Token Rate Limits"}
                  description={USER_GROUP_DESCRIPTION}
                  responseMapper={(data: Record<string, TokenRateLimit[]>) =>
                    Object.entries(data).flatMap(([group_name, elements]) =>
                      elements.map((element) => ({
                        ...element,
                        group_name,
                      }))
                    )
                  }
                />
              ),
            },
          }}
          value={tabIndex.toString()}
          onValueChange={(val) => setTabIndex(parseInt(val))}
        />
      ) : (
        <GenericTokenRateLimitTable
          fetchUrl={GLOBAL_TOKEN_FETCH_URL}
          title={"Global Token Rate Limits"}
          description={GLOBAL_DESCRIPTION}
        />
      )}

      <CreateRateLimitModal
        isOpen={modalIsOpen}
        setIsOpen={() => setModalIsOpen(false)}
        onSubmit={handleSubmit}
        forSpecificScope={
          isPaidEnterpriseFeaturesEnabled ? undefined : Scope.GLOBAL
        }
      />
    </Section>
  );
}

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header title={route.title} icon={route.icon} divider />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
