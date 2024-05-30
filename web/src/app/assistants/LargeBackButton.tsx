"use client";

import { useRouter } from "next/navigation";
import { FiChevronLeft } from "react-icons/fi";

export function LargeBackButton() {
  const router = useRouter();
  return (
    <div className="cursor-pointer" onClick={() => router.back()}>
      <FiChevronLeft
        className="mr-1 my-auto p-1 hover:bg-hover rounded cursor-pointer"
        size={32}
      />
    </div>
  );
}
