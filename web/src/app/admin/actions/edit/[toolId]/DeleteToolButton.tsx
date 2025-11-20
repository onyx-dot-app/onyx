"use client";

import Button from "@/refresh-components/buttons/Button";
import { deleteCustomTool } from "@/lib/tools/edit";
import { useRouter } from "next/navigation";
import SvgTrash from "@/icons/trash";

export function DeleteToolButton({ toolId }: { toolId: number }) {
  const router = useRouter();

  return (
    <Button
      danger
      onClick={async () => {
        const response = await deleteCustomTool(toolId);
        if (response.data) {
          router.push(`/admin/actions?u=${Date.now()}`);
        } else {
          alert(`Failed to delete tool - ${response.error}`);
        }
      }}
      leftIcon={SvgTrash}
    >
      Delete
    </Button>
  );
}
