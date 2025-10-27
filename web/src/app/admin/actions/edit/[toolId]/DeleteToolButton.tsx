"use client";

import { Button } from "@/components/ui/button";
import { FiTrash } from "react-icons/fi";
import { deleteCustomTool } from "@/lib/tools/edit";
import { useRouter } from "next/navigation";

export function DeleteToolButton({ toolId }: { toolId: number }) {
  const router = useRouter();

  return (
    <Button
      variant="destructive"
      size="sm"
      onClick={async () => {
        try {
          if (!confirm("Are you sure you want to delete this tool?")) return;
          const response = await deleteCustomTool(toolId);
          if (response.data) {
            if (window.location.pathname === "/actions") {
              router.refresh();
            } else {
              router.push("/actions");
            }
          } else {
            alert(`Failed to delete tool: ${response.error}`);
          }
        } catch (error) {
          console.error(error);
          alert("Unexpected error occurred while deleting the tool.");
        }
      }}
      icon={FiTrash}
    >
      Delete
    </Button>
  );
}
