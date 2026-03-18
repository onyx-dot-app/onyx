"use client";

import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import { REGISTRATION_URL } from "@/lib/constants";
import { Button } from "@opal/components";
import Link from "next/link";
import { SvgImport } from "@opal/icons";

export default function Page() {
  return (
    <AuthFlowContainer>
      <div className="flex flex-col space-y-6">
        <h2 className="text-2xl font-bold text-text-900 text-center">
          Account Not Found
        </h2>
        <p className="text-text-700 max-w-md text-center">
          No encontramos tu cuenta en nuestros registros. Para acceder a la
          aplicación, necesitas:
        </p>
        <ul className="list-disc text-left text-text-600 w-full pl-6 mx-auto">
          <li>Recibir una invitación a un equipo existente</li>
          <li>Crear un nuevo equipo</li>
        </ul>
        <div className="flex justify-center">
          <Button
            href={`${REGISTRATION_URL}/register`}
            width="full"
            icon={SvgImport}
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
