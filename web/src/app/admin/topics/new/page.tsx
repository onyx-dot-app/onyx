"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { toast } from "@/hooks/useToast";
import { createTopic } from "../lib";

export default function NewTopicPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [watchPath, setWatchPath] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await createTopic({ name, description, watch_path: watchPath });
      if (res.ok) {
        toast.success("Topic created");
        router.push("/admin/topics");
      } else {
        const err = await res.json().catch(() => ({}));
        toast.error(`Failed: ${err.detail ?? res.status}`);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={ADMIN_ROUTES.TOPICS.icon}
        title="New Topic"
        backButton
        onBack={() => router.push("/admin/topics")}
        divider
      />
      <SettingsLayouts.Body>
        <form onSubmit={handleSubmit} className="max-w-lg space-y-4">
          <div>
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="watchPath">Watch Path</Label>
            <Input
              id="watchPath"
              value={watchPath}
              onChange={(e) => setWatchPath(e.target.value)}
              placeholder="/raw/my-topic"
              required
            />
            <p className="text-sm text-muted-foreground mt-1">
              Path inside the container where raw documents are placed (e.g. /raw/trading).
            </p>
          </div>
          <Button type="submit" disabled={submitting}>
            {submitting ? "Creating…" : "Create Topic"}
          </Button>
        </form>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
