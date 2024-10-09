"use client";

import { Modal } from "../../Modal";
import Link from "next/link";
import { useEffect, useState } from "react";
import { CCPairBasicInfo } from "@/lib/types";
import { useRouter } from "next/navigation";

export function NoCompleteSourcesModal({
  ccPairs,
}: {
  ccPairs: CCPairBasicInfo[];
}) {
  const router = useRouter();
  const [isHidden, setIsHidden] = useState(false);

  useEffect(() => {
    const interval = setInterval(() => {
      router.refresh();
    }, 5000);

    return () => clearInterval(interval);
  }, [router]);

  if (isHidden) {
    return null;
  }

  const totalDocs = ccPairs.reduce(
    (acc, ccPair) => acc + ccPair.docs_indexed,
    0
  );

  return (
    <Modal
      className="max-w-4xl"
      title="⏳ None of your connectors have finished a full sync yet"
      onOutsideClick={() => setIsHidden(true)}
    >
      <div className="text-sm">
        <div>
          <div>
            You&apos;ve connected some sources, but none of them have finished
            syncing. Depending on the size of the knowledge base(s) you&apos;ve
            connected to Danswer, it can take anywhere between 30 seconds to a
            few days for the initial sync to complete. So far we&apos;ve synced{" "}
            <b>{totalDocs}</b> documents.
            <br />
            <br />
            To view the status of your syncing connectors, head over to the{" "}
            <Link className="text-link" href="admin/indexing/status">
              Existing Connectors page
            </Link>
            .
            <br />
            <br />
            <p
              className="text-link cursor-pointer inline"
              onClick={() => {
                setIsHidden(true);
              }}
            >
              Or, click here to continue and ask questions on the partially
              synced knowledge set.
            </p>
          </div>
        </div>
      </div>
    </Modal>
  );
}
