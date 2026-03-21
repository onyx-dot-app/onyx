import Link from "next/link";
import { OnyxIcon as ActivaIcon } from "@/components/icons/icons";
import landingStyles from "@/app/Landing.module.css";
import { cn } from "@/lib/utils";
import { DEFAULT_APPLICATION_NAME } from "@/lib/constants";
import styles from "@/components/auth/AuthFlowContainer.module.css";

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
    <div
      className={cn(
        landingStyles.landingFuture,
        styles.authFuture,
        "relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-4 py-12 text-[var(--landing-text)] lg:py-16"
      )}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[34rem] bg-[radial-gradient(circle_at_top,_var(--landing-bg-top),_transparent_68%)]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-20 h-[24rem] w-[24rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,_var(--landing-bg-spot),_transparent_72%)]"
      />

      <div className="relative mx-auto w-full max-w-7xl">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)] lg:items-center lg:gap-16">
          <div className="max-w-3xl">
            <Link
              href="/"
              className="inline-flex items-center gap-3 text-[var(--landing-text)]"
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-12 border border-[color:var(--landing-border)] bg-[color:var(--landing-card-solid)] shadow-[0_18px_40px_-28px_rgba(67,106,201,0.55)]">
                <ActivaIcon size={28} className="shrink-0" />
              </span>
              <span className="flex flex-col">
                <span className="text-2xl font-semibold tracking-[-0.08em]">
                  {DEFAULT_APPLICATION_NAME}
                </span>
                <span className="text-xs uppercase tracking-[0.24em] text-[var(--landing-muted)]">
                  IA operativa
                </span>
              </span>
            </Link>

            <div className="mt-8 inline-flex items-center rounded-full border border-[color:var(--landing-border)] bg-[var(--landing-accent-pale)] px-4 py-2 text-sm font-medium text-[var(--landing-accent-strong)] shadow-[0_18px_40px_-28px_rgba(67,106,201,0.55)]">
              Menos busqueda. Mas ejecucion.
            </div>

            <p className="pt-12 text-xs font-semibold uppercase tracking-[0.28em] text-[var(--landing-accent-strong)]">
              ACTIVA / IA operativa
            </p>

            <h1 className="pt-8 text-[clamp(3rem,6vw,5.25rem)] font-semibold leading-[0.94] tracking-[-0.07em] text-[var(--landing-text)]">
              Opera con contexto.
              <br />
              Decide con claridad.
            </h1>

            <p className="max-w-2xl pt-8 text-[clamp(1.02rem,2vw,1.22rem)] leading-[1.75] text-[var(--landing-muted)]">
              El acceso a ACTIVA deberia sentirse parte del producto, no una
              pantalla aparte. Entra a tu espacio de trabajo con la misma
              identidad visual y la misma sensacion operativa de la landing.
            </p>

            <div className="flex flex-wrap gap-3 pt-10">
              <span className="rounded-full border border-[color:var(--landing-border)] bg-[var(--landing-accent-pale)] px-4 py-2 text-sm font-medium text-[var(--landing-accent-strong)]">
                Evidencia interna
              </span>
              <span className="rounded-full border border-[color:var(--landing-border)] bg-[var(--landing-accent-pale)] px-4 py-2 text-sm font-medium text-[var(--landing-accent-strong)]">
                Acciones con control
              </span>
              <span className="rounded-full border border-[color:var(--landing-border)] bg-[var(--landing-accent-pale)] px-4 py-2 text-sm font-medium text-[var(--landing-accent-strong)]">
                Auditoria completa
              </span>
            </div>
          </div>

          <div className="w-full max-w-[32rem] justify-self-end">
            <div className="rounded-16 border border-[color:var(--landing-border)] bg-[color:var(--landing-card)] p-5 shadow-[0_34px_70px_-32px_rgba(33,64,120,0.55)] backdrop-blur-sm">
              <div className="rounded-16 border border-[color:var(--landing-border)] bg-[image:var(--landing-card-tint)] p-6 md:p-7">
                <div className="w-full">{children}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      {authState === "login" && (
        <div className="mx-auto w-full max-w-[32rem] pt-5 text-center text-sm text-[var(--landing-muted)] mainUiBody lg:pr-0">
          {footerContent ?? (
            <>
              {`Nuevo en ${DEFAULT_APPLICATION_NAME}?`}{" "}
              <Link
                href="/auth/signup"
                className="text-[var(--landing-accent)] mainUiAction underline decoration-[color:var(--landing-border-strong)] underline-offset-4 transition-colors duration-200 hover:text-[var(--landing-accent-strong)]"
              >
                Crea tu cuenta
              </Link>
            </>
          )}
        </div>
      )}
      {authState === "signup" && (
        <div className="mx-auto w-full max-w-[32rem] pt-5 text-center text-sm text-[var(--landing-muted)] mainUiBody lg:pr-0">
          Ya tienes cuenta?{" "}
          <Link
            href="/auth/login?autoRedirectToSignup=false"
            className="text-[var(--landing-accent)] mainUiAction underline decoration-[color:var(--landing-border-strong)] underline-offset-4 transition-colors duration-200 hover:text-[var(--landing-accent-strong)]"
          >
            Inicia sesion
          </Link>
        </div>
      )}
    </div>
  );
}
