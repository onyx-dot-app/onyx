import ScheduledTaskEditor from "@/sections/scheduledTasks/ScheduledTaskEditor";

interface PageProps {
  params: Promise<{ taskId: string }>;
}

export default async function Page({ params }: PageProps) {
  const { taskId } = await params;
  return <ScheduledTaskEditor key={taskId} taskId={taskId} />;
}
