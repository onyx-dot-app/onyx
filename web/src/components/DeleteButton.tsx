"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../i18n/keys";
import { FiTrash } from "react-icons/fi";

export function DeleteButton({
  onClick,
  disabled,
}: {
  onClick?: (event: React.MouseEvent<HTMLElement>) => void | Promise<void>;
  disabled?: boolean;
}) {
  const { t } = useTranslation();

  return (
    <div
      className={`
        my-auto 
        flex 
        mb-1 
        ${
          disabled
            ? "cursor-default"
            : "hover:bg-accent-background-hovered cursor-pointer"
        } 
        w-fit 
        p-2 
        rounded-lg
        border-border
        text-sm`}
      onClick={onClick}
    >
      <FiTrash className="mr-1 my-auto" />
      {t(k.DELETE)}
    </div>
  );
}
