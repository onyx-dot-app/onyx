"use client";
import i18n from "@/i18n/init";
import k from "@/i18n/keys";

import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import { REGISTRATION_URL } from "@/lib/constants";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { FiLogIn } from "react-icons/fi";

const Page = () => {
  return (
    <AuthFlowContainer>
      <div className="flex flex-col space-y-6">
        <h2 className="text-2xl font-bold text-text-900 text-center">
          {i18n.t(k.ACCOUNT_NOT_FOUND)}
        </h2>
        <p className="text-text-700 max-w-md text-center">
          {i18n.t(k.WE_COULDN_T_FIND_YOUR_ACCOUNT)}
        </p>
        <ul className="list-disc text-left text-text-600 w-full pl-6 mx-auto">
          <li>{i18n.t(k.BE_INVITED_TO_AN_EXISTING_ONYX)}</li>
          <li>{i18n.t(k.CREATE_A_NEW_ONYX_TEAM)}</li>
        </ul>
        <div className="flex justify-center">
          <Link
            href={`${REGISTRATION_URL}/register`}
            className="w-full max-w-xs"
          >
            <Button size="lg" icon={FiLogIn} className="w-full">
              {i18n.t(k.CREATE_NEW_ORGANIZATION)}
            </Button>
          </Link>
        </div>
        <p className="text-sm text-text-500 text-center">
          {i18n.t(k.HAVE_AN_ACCOUNT_WITH_A_DIFFERE)}{" "}
          <Link href="/auth/login" className="text-indigo-600 hover:underline">
            {i18n.t(k.SIGN_IN)}
          </Link>
        </p>
      </div>
    </AuthFlowContainer>
  );
};

export default Page;
