import { request, type FullConfig } from "@playwright/test";
import { TEST_ADMIN_CREDENTIALS } from "@tests/e2e/constants";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  putMockLlmDefaultScript,
  waitForMockLlmServer,
} from "@tests/e2e/utils/mockLlm";

export default async function setup(config: FullConfig): Promise<void> {
  const baseURL = config.projects[0]?.use.baseURL;
  const client = await request.newContext({ baseURL });
  try {
    const { email, password } = TEST_ADMIN_CREDENTIALS;
    const registration = await client.post("/api/auth/register", {
      data: { email, username: email, password },
    });
    if (
      !registration.ok() &&
      !(await registration.text()).includes("REGISTER_USER_ALREADY_EXISTS")
    ) {
      throw new Error(
        `Stack registration failed: HTTP ${registration.status()}`
      );
    }
    const login = await client.post("/api/auth/login", {
      form: { username: email, password },
    });
    if (!login.ok()) {
      throw new Error(`Stack login failed: HTTP ${login.status()}`);
    }
    const profile = await client.patch("/api/user/personalization", {
      data: { name: "Admin" },
    });
    if (!profile.ok()) {
      throw new Error(`Stack profile setup failed: HTTP ${profile.status()}`);
    }
    if (process.env.MOCK_LLM_SERVER_URL) {
      await waitForMockLlmServer();
      await putMockLlmDefaultScript();
      await new OnyxApiClient(client, baseURL).ensurePublicProvider();
    }
  } finally {
    await client.dispose();
  }
}
