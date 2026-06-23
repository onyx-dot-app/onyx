"use client";

import SimpleTabs from "@/refresh-components/SimpleTabs";
import { SettingsLayouts } from "@opal/layouts";
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
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import { SvgGlobe, SvgPlusCircle, SvgUser, SvgUsers } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

import { useTranslation } from "react-i18next";

const route = ADMIN_ROUTES.TOKEN_RATE_LIMITS;
const GLOBAL_TOKEN_FETCH_URL = SWR_KEYS.globalTokenRateLimits;
const USER_TOKEN_FETCH_URL = SWR_KEYS.userTokenRateLimits;
const USER_GROUP_FETCH_URL = SWR_KEYS.userGroupTokenRateLimits;

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
  const { t } = useTranslation();
  const [tabIndex, setTabIndex] = useState(0);
  const [modalIsOpen, setModalIsOpen] = useState(false);

  const enterpriseTier = useTierAtLeast(Tier.ENTERPRISE);

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
        toast.success(t("admin.token_rate_limits.success_toast"));
        updateTable(target_scope);
      })
      .catch((error) => {
        toast.error(error.message);
      });
  };

  return (
    <Section alignItems="stretch" justifyContent="start" height="auto">
      <Text as="p">
        {t("admin.token_rate_limits.description")}
      </Text>

      <ul className="list-disc ml-4">
        <li>
          <Text as="p">
            {t("admin.token_rate_limits.list_global")}
          </Text>
        </li>
        {enterpriseTier && (
          <>
            <li>
              <Text as="p">
                {t("admin.token_rate_limits.list_user")}
              </Text>
            </li>
            <li>
              <Text as="p">
                {t("admin.token_rate_limits.list_group")}
              </Text>
            </li>
          </>
        )}
        <li>
          <Text as="p">{t("admin.token_rate_limits.list_on_the_fly")}</Text>
        </li>
      </ul>

      <Button
        icon={SvgPlusCircle}
        prominence="secondary"
        onClick={() => setModalIsOpen(true)}
      >
        {t("admin.token_rate_limits.create_btn")}
      </Button>

      {enterpriseTier ? (
        <SimpleTabs
          tabs={{
            "0": {
              name: t("admin.token_rate_limits.tab_global"),
              icon: SvgGlobe,
              content: (
                <GenericTokenRateLimitTable
                  fetchUrl={GLOBAL_TOKEN_FETCH_URL}
                  title={t("admin.token_rate_limits.global_title")}
                  description={t("admin.token_rate_limits.global_desc")}
                />
              ),
            },
            "1": {
              name: t("admin.token_rate_limits.tab_user"),
              icon: SvgUser,
              content: (
                <GenericTokenRateLimitTable
                  fetchUrl={USER_TOKEN_FETCH_URL}
                  title={t("admin.token_rate_limits.user_title")}
                  description={t("admin.token_rate_limits.user_desc")}
                />
              ),
            },
            "2": {
              name: t("admin.token_rate_limits.tab_groups"),
              icon: SvgUsers,
              content: (
                <GenericTokenRateLimitTable
                  fetchUrl={USER_GROUP_FETCH_URL}
                  title={t("admin.token_rate_limits.group_title")}
                  description={t("admin.token_rate_limits.group_desc")}
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
          title={t("admin.token_rate_limits.global_title")}
          description={t("admin.token_rate_limits.global_desc")}
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
