"use client";

import { useTranslations } from "next-intl";
import SimpleTabs from "@/refresh-components/SimpleTabs";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Text } from "@opal/components";
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
import CreateButton from "@/refresh-components/buttons/CreateButton";
import { SvgGlobe, SvgUser, SvgUsers } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

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
  const t = useTranslations("admin.rateLimits");
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
        toast.success(t("created"));
        updateTable(target_scope);
      })
      .catch((error) => {
        toast.error(error.message);
      });
  };

  return (
    <Section alignItems="stretch" justifyContent="start" height="auto">
      <Text as="p">
        {t("description")}
      </Text>

      <ul className="list-disc ml-4">
        <li>
          <Text as="p">
            {t("setGlobalLimit")}
          </Text>
        </li>
        {isPaidEnterpriseFeaturesEnabled && (
          <>
            <li>
              <Text as="p">
                {t("setUserLimit")}
              </Text>
            </li>
            <li>
              <Text as="p">
                {t("setGroupLimit")}
              </Text>
            </li>
          </>
        )}
        <li>
          <Text as="p">{t("enableDisable")}</Text>
        </li>
      </ul>

      <CreateButton onClick={() => setModalIsOpen(true)}>
        {t("createButton")}
      </CreateButton>

      {isPaidEnterpriseFeaturesEnabled ? (
        <SimpleTabs
          tabs={{
            "0": {
              name: t("tabGlobal"),
              icon: SvgGlobe,
              content: (
                <GenericTokenRateLimitTable
                  fetchUrl={GLOBAL_TOKEN_FETCH_URL}
                  title={t("globalTitle")}
                  description={t("globalDescription")}
                />
              ),
            },
            "1": {
              name: t("tabUser"),
              icon: SvgUser,
              content: (
                <GenericTokenRateLimitTable
                  fetchUrl={USER_TOKEN_FETCH_URL}
                  title={t("userTitle")}
                  description={t("userDescription")}
                />
              ),
            },
            "2": {
              name: t("tabUserGroups"),
              icon: SvgUsers,
              content: (
                <GenericTokenRateLimitTable
                  fetchUrl={USER_GROUP_FETCH_URL}
                  title={t("userGroupTitle")}
                  description={t("userGroupDescription")}
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
          title={t("globalTitle")}
          description={t("globalDescription")}
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
      <SettingsLayouts.Header title={route.title} icon={route.icon} separator />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
