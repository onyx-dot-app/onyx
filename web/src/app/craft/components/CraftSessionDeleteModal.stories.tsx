import type { Meta, StoryObj } from "@storybook/react-vite";
import { CraftSessionDeleteModal } from "@/app/craft/components/SideBar";

const meta: Meta<typeof CraftSessionDeleteModal> = {
  title: "Apps/Craft/Session/Delete Confirmation",
  component: CraftSessionDeleteModal,
  tags: ["autodocs"],
  args: {
    sessionTitle: "Quarterly planning dashboard",
    isDeleting: false,
    onClose: () => {},
    onConfirm: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof CraftSessionDeleteModal>;

export const Playground: Story = {};
