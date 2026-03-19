import Link from "next/link";
import { DEFAULT_APPLICATION_NAME } from "@/lib/constants";

interface AuthFlowContainerProps {
  children: React.ReactNode;
  authState?: "signup" | "login" | "join";
  footerContent?: React.ReactNode;
}

export default function AuthFlowContainer({
  children,
  authState,
  footerContent,
}: AuthFlowContainerProps) {
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-background-neutral-00 px-4 py-12 lg:py-16">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[34rem] bg-[radial-gradient(circle_at_top,_var(--theme-orange-01),_transparent_68%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-20 h-[24rem] w-[24rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,_var(--theme-amber-01),_transparent_72%)]"
      />

      <div className="relative mx-auto w-full max-w-7xl">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)] lg:items-center lg:gap-16">
          <div className="max-w-3xl">
            <Link href="/" className="inline-flex items-center gap-3 text-text-05">
              <span className="flex h-11 w-11 items-center justify-center rounded-12 bg-theme-orange-04 text-sm font-semibold tracking-[0.12em] text-activa-ink-100">
                A
              </span>
              <span className="flex flex-col">
                <span className="text-2xl font-semibold tracking-[-0.08em]">
                  {DEFAULT_APPLICATION_NAME}
                </span>
                <span className="text-xs uppercase tracking-[0.24em] text-text-03">
                  IA operativa
                </span>
              </span>
            </Link>

            <div className="mt-8 inline-flex items-center rounded-full border border-theme-orange-02 bg-theme-orange-01 px-4 py-2 text-sm font-medium text-theme-orange-05 shadow-01">
              Menos busqueda. Mas ejecucion.
            </div>

            <p className="pt-12 text-xs font-semibold uppercase tracking-[0.28em] text-text-03">
              ACTIVA / IA operativa
            </p>

            <h1 className="pt-8 text-[clamp(3rem,6vw,5.25rem)] font-semibold leading-[0.94] tracking-[-0.07em] text-text-05">
              Opera con contexto.
              <br />
              Decide con claridad.
            </h1>

            <p className="max-w-2xl pt-8 text-[clamp(1.02rem,2vw,1.22rem)] leading-[1.75] text-text-03">
              El acceso a ACTIVA deberia sentirse parte del producto, no una
              pantalla aparte. Entra a tu espacio de trabajo con la misma
              identidad visual y la misma sensacion operativa de la landing.
            </p>

            <div className="flex flex-wrap gap-3 pt-10">
              <span className="rounded-full border border-theme-orange-02 bg-theme-orange-01 px-4 py-2 text-sm font-medium text-theme-orange-05">
                Evidencia interna
              </span>
              <span className="rounded-full border border-theme-orange-02 bg-theme-orange-01 px-4 py-2 text-sm font-medium text-theme-orange-05">
                Acciones con control
              </span>
              <span className="rounded-full border border-theme-orange-02 bg-theme-orange-01 px-4 py-2 text-sm font-medium text-theme-orange-05">
                Auditoria completa
              </span>
            </div>
          </div>

          <div className="w-full max-w-[32rem] justify-self-end">
            <div className="rounded-16 border border-border-01 bg-background-neutral-00 p-5 shadow-02">
              <div className="rounded-16 bg-[linear-gradient(180deg,var(--theme-orange-01)_0%,var(--background-neutral-00)_100%)] p-6 md:p-7">
                <div className="w-full">{children}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      {authState === "login" && (
        <div className="mx-auto w-full max-w-[32rem] pt-5 text-center text-sm text-text-03 mainUiBody lg:pr-0">
          {footerContent ?? (
            <>
              {`Nuevo en ${DEFAULT_APPLICATION_NAME}?`}{" "}
              <Link
                href="/auth/signup"
                className="text-theme-orange-05 mainUiAction underline decoration-theme-orange-03 underline-offset-4 transition-colors duration-200 hover:text-theme-orange-04"
              >
                Crea tu cuenta
              </Link>
            </>
          )}
        </div>
      )}
      {authState === "signup" && (
        <div className="mx-auto w-full max-w-[32rem] pt-5 text-center text-sm text-text-03 mainUiBody lg:pr-0">
          Ya tienes cuenta?{" "}
          <Link
            href="/auth/login?autoRedirectToSignup=false"
            className="text-theme-orange-05 mainUiAction underline decoration-theme-orange-03 underline-offset-4 transition-colors duration-200 hover:text-theme-orange-04"
          >
            Inicia sesion
          </Link>
        </div>
      )}
    </div>
  );
}
