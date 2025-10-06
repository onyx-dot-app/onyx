"use client";

import { AdminPageTitle } from "@/components/admin/Title";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import Text from "@/components/ui/text";
import { useState } from "react";
import { FiGlobe, FiUser, FiUsers } from "react-icons/fi";
import {
  insertGlobalTokenRateLimit,
  insertGroupTokenRateLimit,
  insertUserTokenRateLimit,
} from "./lib";
import { Scope, TokenRateLimit } from "./types";
import { GenericTokenRateLimitTable } from "./TokenRateLimitTables";
import { mutate } from "swr";
import { usePopup } from "@/components/admin/connectors/Popup";
import { CreateRateLimitModal } from "./CreateRateLimitModal";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { ShieldIcon } from "@/components/icons/icons";
import CreateButton from "@/refresh-components/buttons/CreateButton";

const BASE_URL = "/api/admin/token-rate-limits";
const GLOBAL_TOKEN_FETCH_URL = `${BASE_URL}/global`;
const USER_TOKEN_FETCH_URL = `${BASE_URL}/users`;
const USER_GROUP_FETCH_URL = `${BASE_URL}/user-groups`;

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
  const { popup, setPopup } = usePopup();

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
        setPopup({ type: "success", message: "Token rate limit created!" });
        updateTable(target_scope);
      })
      .catch((error) => {
        setPopup({ type: "error", message: error.message });
      });
  };

  return (
    <div>
      {popup}

      <Text className="mb-2">
        Token rate limits enable you control how many tokens can be spent in a
        given time period. With token rate limits, you can:
      </Text>

      <ul className="list-disc mt-2 ml-4 mb-2">
        <li>
          <Text>
            Set a global rate limit to control your team&apos;s overall token
            spend.
          </Text>
        </li>
        {isPaidEnterpriseFeaturesEnabled && (
          <>
            <li>
              <Text>
                Set rate limits for users to ensure that no single user can
                spend too many tokens.
              </Text>
            </li>
            <li>
              <Text>
                Set rate limits for user groups to control token spend for your
                teams.
              </Text>
            </li>
          </>
        )}
        <li>
          <Text>Enable and disable rate limits on the fly.</Text>
        </li>
      </ul>

      <CreateButton onClick={() => setModalIsOpen(true)}>
        Create a Token Rate Limit
      </CreateButton>
      {isPaidEnterpriseFeaturesEnabled && (
        <Tabs
          className="mt-2"
          value={tabIndex.toString()}
          onValueChange={(val) => setTabIndex(parseInt(val))}
        >
          <TabsList>
            <TabsTrigger value="0" className="flex items-center gap-2">
              <FiGlobe />
              Global
            </TabsTrigger>
            <TabsTrigger value="1" className="flex items-center gap-2">
              <FiUser />
              User
            </TabsTrigger>
            <TabsTrigger value="2" className="flex items-center gap-2">
              <FiUsers />
              User Groups
            </TabsTrigger>
          </TabsList>
          <TabsContent value="0">
            <GenericTokenRateLimitTable
              fetchUrl={GLOBAL_TOKEN_FETCH_URL}
              title={"Global Token Rate Limits"}
              description={GLOBAL_DESCRIPTION}
            />
          </TabsContent>
          <TabsContent value="1">
            <GenericTokenRateLimitTable
              fetchUrl={USER_TOKEN_FETCH_URL}
              title={"User Token Rate Limits"}
              description={USER_DESCRIPTION}
            />
          </TabsContent>
          <TabsContent value="2">
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
          </TabsContent>
        </Tabs>
      )}

      {!isPaidEnterpriseFeaturesEnabled && (
        <div className="mt-6">
          <GenericTokenRateLimitTable
            fetchUrl={GLOBAL_TOKEN_FETCH_URL}
            title={"Global Token Rate Limits"}
            description={GLOBAL_DESCRIPTION}
          />
        </div>
      )}

      <CreateRateLimitModal
        isOpen={modalIsOpen}
        setIsOpen={() => setModalIsOpen(false)}
        setPopup={setPopup}
        onSubmit={handleSubmit}
        forSpecificScope={
          isPaidEnterpriseFeaturesEnabled ? undefined : Scope.GLOBAL
        }
      />
    </div>
  );
}

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Token Rate Limits"
        icon={<ShieldIcon size={32} />}
      />
      <Main />
    </div>
  );
}
