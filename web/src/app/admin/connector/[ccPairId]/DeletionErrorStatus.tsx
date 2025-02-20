import { FiInfo } from "react-icons/fi";

export default function DeletionErrorStatus({
  deletion_failure_message,
}: {
  deletion_failure_message: string;
}) {
  return (
    <div className="mt-2 rounded-md border border-error-300 bg-error-50 p-4 text-error-600 max-w-3xl">
      <div className="flex items-center">
        <h3 className="text-base font-medium">Deletion Error</h3>
        <div className="ml-2 relative group">
          <FiInfo className="h-4 w-4 text-error-600 cursor-help" />
          <div className="absolute z-10 w-64 p-2 mt-2 text-sm bg-white rounded-md shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-300 border border-background-200">
            This error occurred while attempting to delete the connector. You
            may re-attempt a deletion by clicking the &quot;Delete&quot; button.
          </div>
        </div>
      </div>
      <div className="mt-2 text-sm">
        <p>{deletion_failure_message}</p>
      </div>
    </div>
  );
}
