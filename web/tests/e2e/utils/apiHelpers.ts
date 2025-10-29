import { Page } from "@playwright/test";

/*
 * This file contains function to create and delete LLM providers and user groups via the API.
 * It is used to create and delete test fixtures for the LLM provider tests.
 */

export const createRestrictedProvider = async (
  page: Page,
  providerName: string,
  groupId: number
): Promise<number> => {
  const response = await page.evaluate(
    async ({ name, group_id }) => {
      const res = await fetch("/api/admin/llm/provider?is_creation=true", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          name: name,
          provider: "openai",
          api_key: "test-key",
          default_model_name: "gpt-4o",
          fast_default_model_name: "gpt-4o-mini",
          is_public: false,
          groups: [group_id],
          personas: [],
        }),
      });
      return {
        ok: res.ok,
        status: res.status,
        data: await res.json(),
      };
    },
    { name: providerName, group_id: groupId }
  );

  if (!response.ok) {
    throw new Error(
      `Failed to create provider: ${response.status} - ${JSON.stringify(
        response.data
      )}`
    );
  }

  return response.data.id;
};

export const createUserGroup = async (
  page: Page,
  groupName: string
): Promise<number> => {
  const response = await page.evaluate(
    async ({ name }) => {
      const res = await fetch("/api/manage/admin/user-group", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          name: name,
          user_ids: [],
          cc_pair_ids: [],
        }),
      });
      return {
        ok: res.ok,
        status: res.status,
        data: await res.json(),
      };
    },
    { name: groupName }
  );

  if (!response.ok) {
    throw new Error(
      `Failed to create user group: ${response.status} - ${JSON.stringify(
        response.data
      )}`
    );
  }

  return response.data.id;
};

export const deleteProvider = async (
  page: Page,
  providerId: number
): Promise<void> => {
  await page.evaluate(async (id) => {
    await fetch(`/api/admin/llm/provider/${id}`, {
      method: "DELETE",
      credentials: "include",
    });
  }, providerId);
};

export const deleteUserGroup = async (
  page: Page,
  groupId: number
): Promise<void> => {
  await page.evaluate(async (id) => {
    await fetch(`/api/manage/admin/user-group/${id}`, {
      method: "DELETE",
      credentials: "include",
    });
  }, groupId);
};
