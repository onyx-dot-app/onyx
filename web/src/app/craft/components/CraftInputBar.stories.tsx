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
import type { SkillsList } from "@/lib/skills/types";
import type { PickerEntry } from "@/lib/skills/picker";
import type { ExternalAppType } from "@/app/craft/v1/apps/registry";
import type { LibraryEntry } from "@/app/craft/types/user-library";

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

const libraryTree: LibraryEntry[] = [
  {
    id: "1",
    name: "brand-guidelines.pdf",
    path: "user_library/brand-guidelines.pdf",
    is_directory: false,
    file_size: 2_400_000,
    mime_type: "application/pdf",
    sync_enabled: true,
    created_at: "2026-05-28T00:00:00Z",
  },
  {
    id: "2",
    name: "q2-financials.xlsx",
    path: "user_library/q2-financials.xlsx",
    is_directory: false,
    file_size: 812_000,
    mime_type:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    sync_enabled: true,
    created_at: "2026-05-30T00:00:00Z",
  },
];

const fullFallback = {
  [SWR_KEYS.userSkills]: skillsList,
  [SWR_KEYS.buildExternalApps]: apps,
  [SWR_KEYS.buildUserLibraryTree]: libraryTree,
};

const skillEntry = (slug: string, name: string): PickerEntry => ({
  kind: "skill",
  slug,
  name,
  description: "",
});

const appEntry = (
  slug: string,
  name: string,
  appType: ExternalAppType
): PickerEntry => ({
  kind: "app",
  slug,
  name,
  description: "",
  appType,
  authenticated: true,
});

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

/** Idle input: + button replaces old paperclip; typing /skill opens the picker. */
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

/** Active skill + app chips shown in the strip above the textarea. */
export const WithSkillChips: Story = {
  args: {
    initialEntries: [
      skillEntry("pptx", "PPTX"),
      skillEntry("report-writer", "Report Writer"),
      appEntry("slack", "Slack", "SLACK"),
    ],
  },
};

/** Many chips wrap within the single flush-left row. */
export const WithManySkillChips: Story = {
  args: {
    initialEntries: [
      skillEntry("pptx", "PPTX"),
      skillEntry("pdf", "PDF"),
      skillEntry("report-writer", "Report Writer"),
      skillEntry("data-analysis", "Data Analysis"),
      appEntry("slack", "Slack", "SLACK"),
      appEntry("gmail", "Gmail", "GMAIL"),
      appEntry("github", "GitHub", "GITHUB"),
    ],
  },
};
