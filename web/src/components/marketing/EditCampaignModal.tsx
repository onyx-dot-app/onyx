import React, { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Campaign, UpdateCampaignRequest } from "@/lib/marketing/types";

interface EditCampaignModalProps {
  campaign: Campaign;
  onSubmit: (id: string, data: UpdateCampaignRequest) => void;
  trigger: React.ReactNode;
  open: boolean;
  setOpen: (open: boolean) => void;
  isLoading?: boolean;
}

export default function EditCampaignModal({
  campaign,
  onSubmit,
  trigger,
  open,
  setOpen,
  isLoading = false,
}: EditCampaignModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<"draft" | "active" | "paused" | "completed">("draft");

  useEffect(() => {
    if (campaign) {
      setName(campaign.name);
      setDescription(campaign.description);
      setStatus(campaign.status);
    }
  }, [campaign]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (name.trim() && description.trim()) {
      onSubmit(campaign.id, {
        name: name.trim(),
        description: description.trim(),
        status,
      });
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-[95%] sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Edit Campaign</DialogTitle>
        </DialogHeader>
        <form
          onSubmit={handleSubmit}
          className="flex flex-col justify-stretch space-y-4 w-full"
        >
          <div className="space-y-2 w-full">
            <Label htmlFor="name">Campaign Name</Label>
            <Input
              autoComplete="off"
              id="name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Enter campaign name"
              required
              className="w-full focus-visible:border focus-visible:border-neutral-200 focus-visible:ring-0 !focus:ring-offset-0 !focus:ring-0 !focus:border-0 !focus:ring-transparent !focus:outline-none"
            />
          </div>
          
          <div className="space-y-2 w-full">
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Enter campaign description"
              required
              rows={3}
              className="w-full focus-visible:border focus-visible:border-neutral-200 focus-visible:ring-0 !focus:ring-offset-0 !focus:ring-0 !focus:border-0 !focus:ring-transparent !focus:outline-none"
            />
          </div>

          <div className="space-y-2 w-full">
            <Label htmlFor="status">Status</Label>
            <Select value={status} onValueChange={(value: any) => setStatus(value)}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="draft">Draft</SelectItem>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="paused">Paused</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <Button type="submit" className="w-full" disabled={isLoading}>
            {isLoading ? "Updating..." : "Update Campaign"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
