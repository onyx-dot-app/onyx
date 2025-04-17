"use client";
import i18n from "@/i18n/init";
import k from "./../i18n/keys";

import { FiEdit2 } from "react-icons/fi";

export function EditButton({ onClick }: { onClick: () => void }) {
  return (
    <div
      className={`
        my-auto 
        flex 
        mb-1 
        hover:bg-accent-background-hovered 
        w-fit 
        p-2 
        cursor-pointer 
        rounded-lg
        border-border
        text-sm`}
      onClick={onClick}
    >
      <FiEdit2 className="mr-1 my-auto" />
      {i18n.t(k.EDIT)}
    </div>
  );
}
