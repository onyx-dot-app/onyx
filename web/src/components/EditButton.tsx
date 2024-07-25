"use client";

import { FiEdit2 } from "react-icons/fi";

export function EditButton({ onClick }: { onClick: () => void }) {
  return (
    <div
      className={`
        my-auto 
        flex 
        mb-1 
        hover:bg-hover 
        w-fit 
        p-2 
        cursor-pointer 
        rounded-lg
        border-border
        text-sm`}
      onClick={onClick}
    >
      <FiEdit2 className="mr-1 my-auto" />
      Edit
    </div>
  );
}
