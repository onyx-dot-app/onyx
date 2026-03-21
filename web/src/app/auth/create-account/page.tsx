"use client";

import Link from "next/link";
import { Button } from "@opal/components";
import { SvgImport } from "@opal/icons";

import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import { REGISTRATION_URL } from "@/lib/constants";

export default function Page() {
  return (
    <AuthFlowContainer>
      <div className="flex flex-col space-y-6">
        <h2 className="text-center text-2xl font-bold text-text-05">
          Cuenta no encontrada
        </h2>
        <p className="max-w-md text-center text-text-03">
          No encontramos tu cuenta en nuestros registros. Para acceder a la
          aplicacion, necesitas:
        </p>
        <ul className="mx-auto w-full list-disc pl-6 text-left text-text-03">
          <li>Recibir una invitacion a un equipo existente</li>
          <li>Crear un nuevo equipo</li>
        </ul>
        <div className="flex justify-center">
          <Button
            href={`${REGISTRATION_URL}/register`}
            width="full"
            icon={SvgImport}
          >
            Crear nueva organizacion
          </Button>
        </div>
        <p className="text-center text-sm text-text-03">
          Tienes una cuenta con otro correo?{" "}
          <Link href="/auth/login" className="text-action-link-05 hover:underline">
            Inicia sesion
          </Link>
        </p>
      </div>
    </AuthFlowContainer>
  );
}
