/** @jest-environment jsdom */
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import OpenApiActionCard from "@/sections/actions/OpenApiActionCard";
import type { ToolSnapshot } from "@/lib/tools/types";

const tool: ToolSnapshot = {
  id: 42,
  name: "API",
  display_name: "API",
  description: "API actions",
  definition: {
    openapi: "3.0.3",
    info: { title: "API", version: "1" },
    servers: [{ url: "https://example.com/api" }],
    paths: {
      "/items": {
        get: {
          operationId: "listItems",
          summary: "List items",
          responses: { "200": { description: "Items" } },
        },
      },
    },
  },
  custom_headers: [],
  in_code_tool_id: null,
  passthrough_auth: false,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
  permissions: { edit: true, delete: true, toggle: true, authenticate: true },
};

it("keeps an enabled no-auth action usable and exposes its configuration", async () => {
  const user = setupUser();
  const onManage = jest.fn();
  render(
    <OpenApiActionCard
      tool={tool}
      onAuthenticate={jest.fn()}
      onManage={onManage}
      mutateOpenApiTools={jest.fn()}
    />
  );
  expect(screen.getByText("No authentication configured")).toBeInTheDocument();
  expect(screen.queryByText("Not Authenticated")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /View tools/i })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: /Manage/i }));
  expect(onManage).toHaveBeenCalledWith(tool);
});

it("keeps Craft approval controls out of the Chat action explorer", async () => {
  const user = setupUser();
  render(
    <OpenApiActionCard
      tool={{ ...tool, available_in_craft: true }}
      onAuthenticate={jest.fn()}
      mutateOpenApiTools={jest.fn()}
    />
  );
  await user.click(screen.getByRole("button", { name: /View tools/i }));
  expect(screen.getAllByText("listItems").length).toBeGreaterThan(0);
  expect(screen.queryByRole("button", { name: "Ask" })).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Deny" })
  ).not.toBeInTheDocument();
});
