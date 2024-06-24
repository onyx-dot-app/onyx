"use client";

import { Button } from "@tremor/react";
import Link from "next/link";
import { FiLogIn } from "react-icons/fi";

const Page = () => {
  return (
    <div className="flex flex-col items-center justify-center h-screen">
      <div className="font-bold">
        Unable to login, please try again and/or contact an administrator.
      </div>
      <Link href="/auth/login" className="w-fit">
        <Button className="mt-4" size="xs" icon={FiLogIn}>
          Back to login
        </Button>
      </Link>
    </div>
  );
};

export default Page;
