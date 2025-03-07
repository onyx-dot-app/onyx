import { FiDownload } from "react-icons/fi";

export function DownloadAsCSV() {
  return (
    <a
      href="/api/admin/query-history-csv"
      className="flex ml-auto py-2 px-4 border border-border h-fit cursor-pointer hover:bg-accent-background text-sm"
    >
      <FiDownload className="my-auto mr-2" />
      Download as CSV
    </a>
  );
}
