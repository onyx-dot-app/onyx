import "./spinner.css";

export default function LoadingModal({ content }: { content: string }) {
  return (
    <div className="fixed inset-0 flex items-center justify-center z-50 bg-neutral-900 bg-opacity-30 dark:bg-neutral-950 dark:bg-opacity-50">
      <div className="bg-neutral-100 dark:bg-neutral-800 rounded-xl p-8 shadow-2xl flex items-center gap-4">
        <div className="loader ease-linear rounded-full border-8 border-t-8 border-background-200 h-8 w-8"></div>
        <p className="text-xl font-medium text-neutral-800 dark:text-neutral-100">
          {content}
        </p>
      </div>
    </div>
  );
}
