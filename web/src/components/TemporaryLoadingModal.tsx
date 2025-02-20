export default function TemporaryLoadingModal({
  content,
}: {
  content: string;
}) {
  return (
    <div className="fixed inset-0 flex items-center justify-center z-50 bg-neutral-900 bg-opacity-30 dark:bg-neutral-950 dark:bg-opacity-50">
      <div className="bg-neutral-100 dark:bg-neutral-800 rounded-xl p-8 shadow-2xl flex items-center space-x-6">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-background-950 dark:border-background-50"></div>
        <p className="text-xl font-medium text-neutral-800 dark:text-neutral-100">
          {content}
        </p>
      </div>
    </div>
  );
}
