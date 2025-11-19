"use client";

import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import SvgImport from "@/icons/import";
import { REGISTRATION_URL } from "@/lib/constants";
import Button from "@/refresh-components/buttons/Button";
import Link from "next/link";

export default function Page() {
  return (
    <AuthFlowContainer>
      <div className="flex flex-col space-y-6">
        <h2 className="text-2xl font-bold text-text-900 text-center">
          Account Not Found
        </h2>
        <p className="text-text-700 max-w-md text-center">
          We couldn&apos;t find your account in our records. To access Onyx, you
          need to either:
        </p>
        <ul className="list-disc text-left text-text-600 w-full pl-6 mx-auto">
          <li>Be invited to an existing Onyx team</li>
          <li>Create a new Onyx team</li>
        </ul>
        <div className="flex justify-center">
          <Button
            href={`${REGISTRATION_URL}/register`}
            className="w-full"
            leftIcon={SvgImport}
          >
            Create New Organization
          </Button>
        </div>
        <p className="text-sm text-text-500 text-center">
          Have an account with a different email?{" "}
          <Link
            href="/auth/login"
            className="text-action-link-05 hover:underline"
          >
            Sign in
          </Link>
        </p>
      </div>
    </AuthFlowContainer>
  );
}
