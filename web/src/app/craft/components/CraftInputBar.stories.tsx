import type { Meta, StoryObj } from "@storybook/react";
import { SWRConfig } from "swr";
import { UserProvider } from "@/providers/UserProvider";
import { UploadFilesProvider } from "@/app/craft/contexts/UploadFilesContext";
import CraftInputBar from "@/app/craft/components/CraftInputBar";
import type { BuildFile } from "@/app/craft/contexts/UploadFilesContext";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  appFixture,
  builtinFixture,
  customFixture,
} from "@/lib/skills/__fixtures__/picker";
import type { SkillsList } from "@/refresh-pages/admin/SkillsPage/interfaces";

const SWR_NO_FETCH = {
  provider: () => new Map(),
  revalidateOnMount: false,
  revalidateIfStale: false,
  revalidateOnFocus: false,
  revalidateOnReconnect: false,
};

const skillsList: SkillsList = {
  builtins: [builtinFixture(), builtinFixture({ slug: "pdf", name: "PDF" })],
  customs: [customFixture()],
};

const apps = [
  appFixture({ slug: "slack", app_type: "SLACK" }),
  appFixture({ slug: "gmail", app_type: "GMAIL", authenticated: false }),
];

const fullFallback = {
  [SWR_KEYS.userSkills]: skillsList,
  [SWR_KEYS.buildExternalApps]: apps,
};

const meta: Meta<typeof CraftInputBar> = {
  title: "Apps/Craft/Input Bar/Craft Input Bar",
  component: CraftInputBar,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <SWRConfig value={{ ...SWR_NO_FETCH, fallback: fullFallback }}>
        <UserProvider>
          <UploadFilesProvider>
            <div className="w-[640px]">
              <Story />
            </div>
          </UploadFilesProvider>
        </UserProvider>
      </SWRConfig>
    ),
  ],
  args: {
    onSubmit: (msg: string, files: BuildFile[]) =>
      console.log("submit", { msg, files }),
    isRunning: false,
    placeholder: "Continue the conversation...",
  },
};

export default meta;
type Story = StoryObj<typeof CraftInputBar>;

/** Idle input — + button replaces old paperclip; typing /skill opens the picker. */
export const Default: Story = {};

/** While a response streams: Stop button appears, InterruptHint shows. */
export const Running: Story = {
  args: {
    isRunning: true,
    onInterrupt: () => console.log("interrupt"),
    queuedMessages: [],
    onQueueMessage: (text: string) => console.log("queue", text),
    onRemoveQueuedMessage: (index: number) => console.log("remove", index),
  },
};

/** Interrupt requested: Stop spinner, send disabled. */
export const Interrupting: Story = {
  args: {
    isRunning: true,
    isInterrupting: true,
    onInterrupt: () => console.log("interrupt"),
  },
};

export const Disabled: Story = {
  args: { disabled: true },
};

export const SandboxInitializing: Story = {
  args: { sandboxInitializing: true },
};

export const NoBottomRounding: Story = {
  args: { noBottomRounding: true },
};
