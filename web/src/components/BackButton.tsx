"use client";
import i18n from "@/i18n/init";
import k from "./../i18n/keys";

import { useRouter } from "next/navigation";

import { FiChevronLeft } from "react-icons/fi";

export function BackButton({
  behaviorOverride,
  routerOverride,
}: {
  behaviorOverride?: () => void;
  routerOverride?: string;
}) {
  const router = useRouter();

  return (
    <div
      className={`
        my-auto 
        flex 
        mb-1 
        hover:bg-accent-background 
        w-fit 
        p-1
        pr-2 
        cursor-pointer 
        rounded-lg 
        text-sm`}
      onClick={() => {
        if (behaviorOverride) {
          behaviorOverride();
        } else if (routerOverride) {
          router.push(routerOverride);
        } else {
          router.back();
        }
      }}
    >
      <FiChevronLeft className="mr-1 my-auto" />
      {i18n.t(k.BACK)}
    </div>
  );
}
