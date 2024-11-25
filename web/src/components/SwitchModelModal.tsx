"use client";

import { Button } from "@/components/ui/button";
import Text from "@/components/ui/text";
import { Modal } from "./Modal";
import Link from "next/link";

export function SwitchModelModal({
  embeddingModelName,
}: {
  embeddingModelName: undefined | null | string;
}) {
  return (
    <Modal className="max-w-4xl">
      <div className="text-base">
        <h2 className="text-xl font-bold mb-4 pb-2 border-b border-border flex">
          ❗ Switch Embedding Model ❗
        </h2>
        <Text>
          We&apos;ve detected you are using our old default embedding model (
          <i>{embeddingModelName || "thenlper/gte-small"}</i>). We believe that
          search performance can be dramatically improved by a simple model
          switch.
          <br />
          <br />
          Please click the button below to choose a new model. Don&apos;t worry,
          the re-indexing necessary for the switch will happen in the background
          - your use of Danswer will not be interrupted.
        </Text>

        <div className="flex mt-4">
          <Link href="/admin/models/embedding" className="w-fit mx-auto">
            <Button size="sm">Choose your Embedding Model</Button>
          </Link>
        </div>
      </div>
    </Modal>
  );
}
