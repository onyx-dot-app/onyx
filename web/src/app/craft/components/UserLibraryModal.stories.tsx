import type { Meta, StoryObj } from "@storybook/react";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import UserLibraryModal from "@/app/craft/components/UserLibraryModal";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { LibraryEntry } from "@/app/craft/types/user-library";

// Disable all SWR fetching so the modal renders purely from the provided
// fallback data instead of hitting the live library API.
const SWR_NO_FETCH = {
  provider: () => new Map(),
  revalidateOnMount: false,
  revalidateIfStale: false,
  revalidateOnFocus: false,
  revalidateOnReconnect: false,
};

const libraryTree: LibraryEntry[] = [
  {
    id: "1",
    name: "reports",
    path: "user_library/reports",
    is_directory: true,
    file_size: null,
    mime_type: null,
    sync_enabled: true,
    created_at: "2026-05-28T00:00:00Z",
  },
  {
    id: "2",
    name: "q2-financials.xlsx",
    path: "user_library/reports/q2-financials.xlsx",
    is_directory: false,
    file_size: 812_000,
    mime_type:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    sync_enabled: true,
    created_at: "2026-05-30T00:00:00Z",
  },
  {
    id: "3",
    name: "brand-guidelines.pdf",
    path: "user_library/brand-guidelines.pdf",
    is_directory: false,
    file_size: 2_400_000,
    mime_type: "application/pdf",
    sync_enabled: false,
    created_at: "2026-05-29T00:00:00Z",
  },
];

function withLibrary(tree: LibraryEntry[]) {
  return function Decorator(Story: () => ReactNode) {
    return (
      <SWRConfig
        value={{
          ...SWR_NO_FETCH,
          fallback: { [SWR_KEYS.buildUserLibraryTree]: tree },
        }}
      >
        <Story />
      </SWRConfig>
    );
  };
}

const meta: Meta<typeof UserLibraryModal> = {
  title: "Apps/Craft/User Library Modal",
  component: UserLibraryModal,
  tags: ["autodocs"],
  args: {
    open: true,
    onClose: () => {},
    onChanges: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof UserLibraryModal>;

// Empty state — the click/drag upload dropzone.
export const Empty: Story = {
  decorators: [withLibrary([])],
};

// Populated — file/folder rows with sizes and hover-revealed actions.
export const WithFiles: Story = {
  decorators: [withLibrary(libraryTree)],
};
