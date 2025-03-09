"use client";

import MyDocuments from "./MyDocuments";
import { BackButton } from "@/components/BackButton";

export default function WrappedUserDocuments({}: {}) {
  return (
    <div className="mx-auto w-full">
      <div className="absolute top-4 left-4">
        <BackButton />
      </div>
      <MyDocuments />
    </div>
  );
}
