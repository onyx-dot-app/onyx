"use client";

import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { FiLogIn } from "react-icons/fi";

const Page = () => {
  return (
    <AuthFlowContainer>
      <div className="flex flex-col space-y-6 max-w-md mx-auto">
        <h2 className="text-2xl font-bold text-text-900 text-center">
          Authentication Error
        </h2>
        <p className="text-text-700 text-center">
          We encountered an issue while attempting to log you in.
        </p>
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 shadow-sm">
          <h3 className="text-red-800 font-semibold mb-2">Possible Issues:</h3>
          <ul className="space-y-2">
            <li className="flex items-center text-red-700">
              <div className="w-2 h-2 bg-red-500 rounded-full mr-2"></div>
              Incorrect or expired login credentials
            </li>
            <li className="flex items-center text-red-700">
              <div className="w-2 h-2 bg-red-500 rounded-full mr-2"></div>
              Temporary authentication system disruption
            </li>
            <li className="flex items-center text-red-700">
              <div className="w-2 h-2 bg-red-500 rounded-full mr-2"></div>
              Account access restrictions or permissions
            </li>
          </ul>
        </div>

        <Link href="/auth/login" className="w-full">
          <Button size="lg" icon={FiLogIn} className="w-full">
            Return to Login Page
          </Button>
        </Link>
        <p className="text-sm text-text-500 text-center">
          We recommend trying again. If you continue to experience problems,
          please reach out to your system administrator for assistance.
        </p>
      </div>
    </AuthFlowContainer>
  );
};

export default Page;
