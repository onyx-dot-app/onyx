import { useLayoutEffect, useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SWRConfig, type State } from "swr";
import { UserProvider } from "@/providers/UserProvider";
import { Permission } from "@/lib/types";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";

function SharingStory() {
  const [ready, setReady] = useState(false);
  const [cache] = useState(() => new Map<string, State>());
  useLayoutEffect(() => {
    const originalFetch = window.fetch;
    const mockFetch: typeof fetch = async (input, init) => {
      const path = new URL(
        input instanceof Request ? input.url : String(input),
        window.location.origin
      ).pathname;
      if (path === "/api/me")
        return Response.json({
          id: "admin",
          email: "alex@example.com",
          is_active: true,
          is_verified: true,
          account_type: "standard",
          preferences: {},
          effective_permissions: [Permission.FULL_ADMIN_PANEL_ACCESS],
          admin_capabilities: [],
        });
      if (path === "/api/skills/custom/custom-1/share")
        return Response.json(
          customFixture({
            name: "weekly-research-brief",
            user_permission: "OWNER",
            installation_policy: "DEFAULT",
            owner: { id: "admin", email: "alex@example.com" },
            author_user_id: "admin",
            ownership_vacant: false,
            user_shares: [
              {
                user: { id: "sam", email: "sam@example.com" },
                permission: "EDITOR",
              },
            ],
          })
        );
      if (path === "/api/users") return Response.json([]);
      if (path === "/api/auth/type")
        return Response.json({ auth_type: "disabled" });
      if (path.startsWith("/api/settings")) return Response.json({});
      if (path.startsWith("/api/")) return Response.json([]);
      return originalFetch(input, init);
    };
    window.fetch = mockFetch;
    setReady(true);
    return () => {
      if (window.fetch === mockFetch) window.fetch = originalFetch;
    };
  }, []);
  return ready ? (
    <SWRConfig value={{ provider: () => cache, shouldRetryOnError: false }}>
      <UserProvider>
        <ShareSkillModal
          mode="edit"
          skillId="custom-1"
          open
          onClose={() => undefined}
          onSaved={() => undefined}
        />
      </UserProvider>
    </SWRConfig>
  ) : null;
}

const meta = {
  title: "Skills/Sharing",
  component: SharingStory,
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof SharingStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Organization: Story = {};
