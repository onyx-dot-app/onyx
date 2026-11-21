import ScheduledTaskPage from "@/sections/scheduledTasks/ScheduledTaskPage";

interface PageProps {
  params: Promise<{ taskId: string }>;
}

export default async function Page({ params }: PageProps) {
  const { taskId } = await params;
  return <ScheduledTaskPage key={taskId} taskId={taskId} />;
}
