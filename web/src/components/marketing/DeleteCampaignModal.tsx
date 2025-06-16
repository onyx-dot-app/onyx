import React from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Campaign } from "@/lib/marketing/types";

interface DeleteCampaignModalProps {
  campaign: Campaign;
  onConfirm: (id: string) => void;
  trigger: React.ReactNode;
  open: boolean;
  setOpen: (open: boolean) => void;
  isLoading?: boolean;
}

export default function DeleteCampaignModal({
  campaign,
  onConfirm,
  trigger,
  open,
  setOpen,
  isLoading = false,
}: DeleteCampaignModalProps) {
  const handleConfirm = () => {
    onConfirm(campaign.id);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-[95%] sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>Delete Campaign</DialogTitle>
        </DialogHeader>
        <div className="py-4">
          <p className="text-sm text-muted-foreground">
            Are you sure you want to delete the campaign "{campaign.name}"? This action cannot be undone.
          </p>
        </div>
        <DialogFooter className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => setOpen(false)}
            disabled={isLoading}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleConfirm}
            disabled={isLoading}
          >
            {isLoading ? "Deleting..." : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
