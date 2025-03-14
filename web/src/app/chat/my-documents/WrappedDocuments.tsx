"use client";

import MyDocuments from "./MyDocuments";
import { BackButton } from "@/components/BackButton";
import { useRouter } from "next/navigation";

export default function WrappedUserDocuments() {
  const router = useRouter();
  return (
    <div className="mx-auto w-full">
      <div className="absolute top-4 left-4">
        <BackButton
          behaviorOverride={() => {
            router.push("/chat");
          }}
        />
      </div>
      <MyDocuments />
    </div>
  );
}
