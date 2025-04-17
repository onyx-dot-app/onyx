"use client";
import i18n from "@/i18n/init";
import k from "./../i18n/keys";

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
          {i18n.t(k.SWITCH_EMBEDDING_MODEL)}
        </h2>
        <Text>
          {i18n.t(k.WE_VE_DETECTED_YOU_ARE_USING_O)}
          <i>{embeddingModelName || "thenlper/gte-small"}</i>
          {i18n.t(k.WE_BELIEVE_THAT_S)}

          <br />
          <br />
          {i18n.t(k.PLEASE_CLICK_THE_BUTTON_BELOW)}
        </Text>

        <div className="flex mt-4">
          <Link href="/admin/models/embedding" className="w-fit mx-auto">
            <Button size="sm">{i18n.t(k.CHOOSE_YOUR_EMBEDDING_MODEL)}</Button>
          </Link>
        </div>
      </div>
    </Modal>
  );
}
