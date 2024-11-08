"use client";

import BulkAdd from "@/components/admin/users/BulkAdd";
import { BulkAddTeamspace } from "@/components/admin/users/BulkAddTeamspace";
import { CustomModal } from "@/components/CustomModal";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/use-toast";
import { Plus } from "lucide-react";
import { useState } from "react";
import { mutate } from "swr";

export const AddUserButton = ({
  teamspaceId,
  refreshUsers,
}: {
  teamspaceId?: string | string[];
  refreshUsers: () => void;
}) => {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const { toast } = useToast();
  const onSuccess = () => {
    mutate(
      (key) => typeof key === "string" && key.startsWith("/api/manage/users")
    );
    setIsModalOpen(false);
    toast({
      title: "Users Invited",
      description: "The users have been successfully invited.",
      variant: "success",
    });
  };
  const onFailure = async (res: Response) => {
    const error = (await res.json()).detail;
    toast({
      title: "Invitation Failed",
      description: `Unable to invite users: ${error}`,
      variant: "destructive",
    });
  };

  return (
    <CustomModal
      title="Bulk Add Users"
      onClose={() => setIsModalOpen(false)}
      open={isModalOpen}
      trigger={
        <Button onClick={() => setIsModalOpen(true)}>
          {teamspaceId ? "Add People" : "Invite People"}
        </Button>
      }
    >
      {teamspaceId ? (
        <BulkAddTeamspace
          teamspaceId={teamspaceId}
          refreshUsers={refreshUsers}
          onClose={() => setIsModalOpen(false)}
        />
      ) : (
        <div className="flex flex-col gap-y-3">
          <Label>
            Add the email addresses to import, separated by whitespaces.
          </Label>
          <BulkAdd onSuccess={onSuccess} onFailure={onFailure} />
        </div>
      )}
    </CustomModal>
  );
};