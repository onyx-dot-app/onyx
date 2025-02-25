import Link from "next/link";
import { useUser } from "@/components/user/UserProvider";

export function NoDocuments() {
  const { isAdmin } = useUser();

  return (
    <div className="text-xs py-2 text-neutral-800 dark:text-neutral-200 italic">
      No documents found. This may be because the documents are still indexing
      or syncing.{" "}
      {isAdmin ? (
        <Link href="/admin/indexing/status" className="underline">
          Check indexing status
        </Link>
      ) : (
        <p>Check with your admin</p>
      )}
    </div>
  );
}
