"use client";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import { DeleteButton } from "@/components/DeleteButton";
import { ThreeDotsLoader } from "@/components/Loading";
import { toast } from "@/hooks/useToast";
import { useTopics } from "./hooks";
import { deleteTopic } from "./lib";

const route = ADMIN_ROUTES.TOPICS;

function TopicsTable() {
  const { data, isLoading, error, refreshTopics } = useTopics();
  if (isLoading) return <ThreeDotsLoader />;
  if (error || !data) return <div>Failed to load topics.</div>;
  return (
    <div className="mb-8">
      <div className="mb-4">
        <CreateButton href="/admin/topics/new">New Topic</CreateButton>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Description</TableHead>
            <TableHead>Watch Path</TableHead>
            <TableHead></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((topic) => (
            <TableRow key={topic.id}>
              <TableCell className="font-medium">{topic.name}</TableCell>
              <TableCell>{topic.description}</TableCell>
              <TableCell className="font-mono text-sm">{topic.watch_path}</TableCell>
              <TableCell>
                <DeleteButton
                  onClick={async () => {
                    const res = await deleteTopic(topic.id);
                    if (res.ok) {
                      toast.success(`Topic "${topic.name}" deleted`);
                    } else {
                      const err = await res.json().catch(() => ({}));
                      toast.error(`Delete failed: ${err.detail ?? res.status}`);
                    }
                    refreshTopics();
                  }}
                />
              </TableCell>
            </TableRow>
          ))}
          {data.length === 0 && (
            <TableRow>
              <TableCell colSpan={4} className="text-center text-muted-foreground">
                No topics yet. Create one to get started.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} divider />
      <SettingsLayouts.Body>
        <TopicsTable />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
