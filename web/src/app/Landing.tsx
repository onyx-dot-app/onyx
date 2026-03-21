import type { Route } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { OnyxIcon as ActivaIcon } from "@/components/icons/icons";
import { cn } from "@/lib/utils";
import styles from "./Landing.module.css";

const BRAND_NAME = "ACTIVA";
const BRAND_DESCRIPTOR = "IA operativa";
const LOGIN_ROUTE: Route = "/login";
const REGISTER_ROUTE: Route = "/register";

interface NavItem {
  href: string;
  label: string;
}

interface LandingButtonProps {
  children: ReactNode;
  className?: string;
  href: Route;
  variant?: "primary" | "secondary";
}

interface Feature {
  description: string;
  index: string;
  title: string;
}

interface FeatureCardProps {
  description: string;
  index: string;
  title: string;
}

interface Step {
  description: string;
  number: string;
  title: string;
}

interface StepCardProps extends Step {
  className?: string;
}

interface SecurityItem {
  description: string;
  title: string;
}

interface SecurityCardProps extends SecurityItem {}

interface SectionAnchorProps {
  id: string;
}

const navItems: NavItem[] = [
  { href: "#producto", label: "Producto" },
  { href: "#flujo", label: "Como funciona" },
  { href: "#seguridad", label: "Seguridad" },
];

const features: Feature[] = [
  {
    index: "01",
    title: "Chat con fuentes",
    description: "Haz preguntas y recibe respuestas con fuentes claras.",
  },
  {
    index: "02",
    title: "Acciones operativas",
    description: "Pide una tarea y ejecutala con control y confirmacion.",
  },
  {
    index: "03",
    title: "Permisos y auditoria",
    description: "Todo queda registrado para saber que paso y por que.",
  },
  {
    index: "04",
    title: "Conectores empresariales",
    description: "Conecta documentos, chats, bases de datos y APIs.",
  },
];

const steps: Step[] = [
  {
    number: "01",
    title: "Conecta tu contexto",
    description: "Conecta los documentos y herramientas que ya usa tu equipo.",
  },
  {
    number: "02",
    title: "Consulta con evidencia",
    description: "Pregunta en lenguaje natural y recibe respuestas con fuentes.",
  },
  {
    number: "03",
    title: "Ejecuta con control",
    description: "Convierte una respuesta en una accion con aprobacion y registro.",
  },
];

const securityItems: SecurityItem[] = [
  {
    title: "Respuestas con respaldo",
    description: "Cada respuesta muestra de donde sale la informacion.",
  },
  {
    title: "Acciones con permiso",
    description: "Solo se ejecuta lo que el usuario tiene permitido hacer.",
  },
  {
    title: "Registro completo",
    description: "Queda historial de lo consultado, aprobado y ejecutado.",
  },
];

function LandingButton({
  children,
  className,
  href,
  variant = "primary",
}: LandingButtonProps) {
  return (
    <Link
      href={href}
      className={cn(
        "inline-flex min-h-11 items-center justify-center rounded-full border px-6 py-3 text-sm font-semibold transition-all duration-300",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--landing-accent)] focus-visible:ring-offset-2",
        "focus-visible:ring-offset-[var(--landing-surface)] hover:-translate-y-0.5",
        variant === "primary"
          ? "border-[color:var(--landing-accent)] bg-[var(--landing-accent)] text-[var(--landing-button-text)] shadow-[0_18px_45px_-24px_rgba(51,108,250,0.7)] hover:border-[color:var(--landing-accent-strong)] hover:bg-[var(--landing-accent-strong)]"
          : "border-[color:var(--landing-border-strong)] bg-[color:var(--landing-card-solid)] text-[var(--landing-accent-strong)] shadow-[0_18px_40px_-28px_rgba(67,106,201,0.55)] hover:bg-[color:var(--landing-surface-alt)]",
        className
      )}
    >
      {children}
    </Link>
  );
}

function FeatureCard({ description, index, title }: FeatureCardProps) {
  return (
    <article className="rounded-16 border border-[color:var(--landing-border)] bg-[color:var(--landing-card)] p-6 shadow-[0_24px_55px_-34px_rgba(28,53,102,0.35)] backdrop-blur-sm">
      <div className="inline-flex rounded-full border border-[color:var(--landing-border)] bg-[var(--landing-accent-pale)] px-3 py-1">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--landing-accent-strong)]">
          {index}
        </p>
      </div>
      <h3 className="pt-4 text-[1.45rem] font-semibold tracking-[-0.04em] text-[var(--landing-text)]">
        {title}
      </h3>
      <p className="max-w-[32ch] pt-3 text-[0.98rem] leading-7 text-[var(--landing-muted)]">
        {description}
      </p>
    </article>
  );
}

function StepCard({ className, description, number, title }: StepCardProps) {
  return (
    <article
      className={cn(
        "rounded-16 border border-[color:var(--landing-border)] bg-[color:var(--landing-card-solid)] p-7 shadow-[0_24px_55px_-34px_rgba(28,53,102,0.35)] backdrop-blur-sm",
        className
      )}
    >
      <div className="inline-flex rounded-full border border-[color:var(--landing-border)] bg-[var(--landing-accent-pale)] px-3 py-1">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--landing-accent-strong)]">
          {number}
        </p>
      </div>
      <h3 className="pt-4 text-[1.4rem] font-semibold tracking-[-0.04em] text-[var(--landing-text)]">
        {title}
      </h3>
      <p className="pt-3 text-base leading-7 text-[var(--landing-muted)]">
        {description}
      </p>
    </article>
  );
}

function SecurityCard({ description, title }: SecurityCardProps) {
  return (
    <article className="rounded-16 border border-[color:var(--landing-border)] bg-[linear-gradient(180deg,var(--landing-accent-pale)_0%,var(--landing-surface-alt)_100%)] p-7 shadow-[0_20px_45px_-34px_rgba(51,108,250,0.5)]">
      <h3 className="text-[1.35rem] font-semibold tracking-[-0.04em] text-[var(--landing-text)]">
        {title}
      </h3>
      <p className="pt-3 text-base leading-7 text-[var(--landing-muted)]">
        {description}
      </p>
    </article>
  );
}

function SectionAnchor({ id }: SectionAnchorProps) {
  return (
    <div
      id={id}
      aria-hidden="true"
      className="pointer-events-none absolute -top-24"
    />
  );
}

export default function Landing() {
  const currentYear = new Date().getFullYear();

  return (
    <div
      className={cn(
        styles.landingFuture,
        "min-h-screen text-[var(--landing-text)]"
      )}
    >
      <div className="relative overflow-hidden">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-0 h-[34rem] bg-[radial-gradient(circle_at_top,_var(--landing-bg-top),_transparent_68%)]"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute left-1/2 top-20 h-[24rem] w-[24rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,_var(--landing-bg-spot),_transparent_72%)]"
        />

        <header className="fixed inset-x-0 top-0 z-40 border-b border-[color:var(--landing-border)] bg-[color:var(--landing-surface)] shadow-[0_10px_30px_-24px_rgba(51,108,250,0.45)] backdrop-blur-md">
          <div className="mx-auto flex w-full max-w-7xl items-center justify-between gap-4 px-6 py-4 lg:px-8">
            <Link
              href="/"
              className="flex min-w-0 items-center text-[var(--landing-text)]"
            >
              <span className="flex items-center gap-3">
                <ActivaIcon size={42} className="shrink-0" />
                <span className="hidden min-w-0 flex-col sm:flex">
                  <span className="text-[2rem] font-semibold leading-none tracking-[-0.08em] text-[var(--landing-text)]">
                    {BRAND_NAME}
                  </span>
                  <span className="pl-1 pt-2 text-[0.72rem] font-semibold uppercase tracking-[0.34em] text-[var(--landing-muted)]">
                    {BRAND_DESCRIPTOR}
                  </span>
                </span>
              </span>
            </Link>

            <nav
              aria-label="Navegacion principal"
              className="hidden items-center gap-10 md:flex"
            >
              {navItems.map((item) => (
                <a
                  key={item.label}
                  href={item.href}
                  className="text-base font-medium text-[var(--landing-muted)] transition-colors hover:text-[var(--landing-accent)]"
                >
                  {item.label}
                </a>
              ))}
            </nav>

            <div className="flex items-center gap-3">
              <LandingButton
                href={LOGIN_ROUTE}
                variant="secondary"
                className="px-4 py-2 md:px-5"
              >
                Iniciar sesion
              </LandingButton>
              <LandingButton
                href={REGISTER_ROUTE}
                className="px-4 py-2 md:px-5"
              >
                Comenzar gratis
              </LandingButton>
            </div>
          </div>
        </header>

        <main className="pt-20">
          <section className="relative px-6 pb-10 pt-14 lg:px-8 lg:pb-12 lg:pt-16">
            <div className="mx-auto grid w-full max-w-7xl gap-10 lg:grid-cols-[minmax(0,1.02fr)_minmax(0,0.98fr)] lg:items-center xl:gap-14">
              <div className="max-w-3xl">
                <h1 className="pt-2 text-[clamp(2.8rem,6.2vw,5.2rem)] font-semibold leading-[0.94] tracking-[-0.07em] text-[var(--landing-text)]">
                  Tu copiloto operativo
                  <br />
                  para trabajar con claridad
                </h1>

                <p className="max-w-xl pt-6 text-[clamp(1.05rem,2vw,1.28rem)] leading-[1.7] text-[var(--landing-muted)]">
                  ACTIVA te ayuda a buscar informacion, entenderla y convertirla
                  en una accion sin saltar entre herramientas.
                </p>

                <div className="flex flex-wrap items-center gap-4 pt-8">
                  <LandingButton
                    href={LOGIN_ROUTE}
                    variant="secondary"
                    className="px-8 py-3"
                  >
                    Iniciar sesion
                  </LandingButton>
                  <LandingButton href={REGISTER_ROUTE} className="px-8 py-3">
                    Crear cuenta gratis
                  </LandingButton>
                </div>
              </div>

              <div className="w-full max-w-[36rem] justify-self-end">
                <div className="rounded-16 border border-[color:var(--landing-border)] bg-[color:var(--landing-card)] p-5 shadow-[0_34px_70px_-32px_rgba(33,64,120,0.55)] backdrop-blur-sm">
                  <div className="rounded-16 border border-[color:var(--landing-border)] bg-[image:var(--landing-card-tint)] p-5">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--landing-accent-strong)]">
                        Vista operativa
                      </p>
                      <h2 className="pt-4 text-[1.75rem] font-semibold leading-[1.12] tracking-[-0.05em] text-[var(--landing-text)]">
                        Mas contexto. Menos friccion.
                      </h2>

                      <div className="pt-5">
                        <div className="rounded-12 border border-[color:var(--landing-border)] bg-[color:var(--landing-card-solid)] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.25)]">
                          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--landing-accent-strong)]">
                            Consulta
                          </p>
                          <p className="pt-2 text-sm leading-6 text-[var(--landing-muted)]">
                            Muestrame las cuentas vencidas y dime cual es el
                            siguiente paso recomendado.
                          </p>
                        </div>
                      </div>

                      <div className="pt-4">
                        <div className="rounded-12 border border-[color:var(--landing-border-strong)] bg-[color:var(--landing-response)] p-5 shadow-[0_18px_35px_-28px_rgba(51,108,250,0.55)]">
                          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--landing-accent)]">
                            Respuesta
                          </p>
                          <p className="pt-3 text-base leading-7 text-[var(--landing-text)]">
                            Hay 14 cuentas criticas. Recomiendo enviar un
                            recordatorio con aprobacion y dejar registro de la
                            accion.
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="relative bg-transparent px-6 pb-20 pt-8 lg:px-8 lg:pb-20 lg:pt-10">
            <SectionAnchor id="producto" />

            <div className="mx-auto w-full max-w-7xl">
              <div className="pb-12">
                <p className="text-xs font-semibold uppercase tracking-[0.26em] text-[var(--landing-accent-strong)]">
                  Producto
                </p>
                <h2 className="pt-4 text-[clamp(2.2rem,4vw,3.6rem)] font-semibold leading-[1.04] tracking-[-0.06em] text-[var(--landing-text)] lg:whitespace-nowrap">
                  Mas texto util. Menos interfaz{"\u00A0"}vacia.
                </h2>
                <p className="max-w-2xl pt-5 text-lg leading-8 text-[var(--landing-muted)]">
                  ACTIVA responde preguntas, conecta herramientas y ayuda a
                  ejecutar tareas con informacion real.
                </p>
              </div>

              <div className="grid gap-6 md:grid-cols-2">
                {features.map((feature) => (
                  <FeatureCard
                    key={feature.title}
                    description={feature.description}
                    index={feature.index}
                    title={feature.title}
                  />
                ))}
              </div>
            </div>
          </section>

          <section className="relative border-t border-[color:var(--landing-border)] bg-[color:var(--landing-surface-alt)] px-6 py-16 lg:px-8 lg:py-[4.5rem]">
            <SectionAnchor id="flujo" />

            <div className="mx-auto grid w-full max-w-7xl gap-10 lg:grid-cols-[minmax(0,0.82fr)_minmax(0,1.18fr)] lg:items-start">
              <div className="max-w-2xl">
                <p className="text-xs font-semibold uppercase tracking-[0.26em] text-[var(--landing-accent-strong)]">
                  Como funciona
                </p>
                <h2 className="pt-4 text-[clamp(2.2rem,4vw,3.5rem)] font-semibold leading-[1.04] tracking-[-0.06em] text-[var(--landing-text)]">
                  De la consulta a la ejecucion en tres pasos.
                </h2>
                <p className="pt-5 text-lg leading-8 text-[var(--landing-muted)]">
                  Pasa de una pregunta a una accion en el mismo flujo, sin abrir
                  cinco herramientas distintas.
                </p>
              </div>

              <div className="grid gap-6 lg:grid-cols-2">
                {steps.map((step, index) => (
                  <StepCard
                    className={cn(index === steps.length - 1 && "lg:col-span-2")}
                    key={step.number}
                    description={step.description}
                    number={step.number}
                    title={step.title}
                  />
                ))}
              </div>
            </div>
          </section>

          <section className="relative border-t border-[color:var(--landing-border)] bg-transparent px-6 py-20 lg:px-8">
            <SectionAnchor id="seguridad" />

            <div className="mx-auto w-full max-w-7xl">
              <div className="pb-12">
                <p className="text-xs font-semibold uppercase tracking-[0.26em] text-[var(--landing-accent-strong)]">
                  Seguridad
                </p>
                <h2 className="pt-4 text-[clamp(2.2rem,4vw,3.5rem)] font-semibold leading-[1.04] tracking-[-0.06em] text-[var(--landing-text)]">
                  Hecha para operar con respaldo.
                </h2>
                <p className="max-w-2xl pt-5 text-lg leading-8 text-[var(--landing-muted)]">
                  No se trata solo de responder. Se trata de hacerlo con control
                  cuando trabajas con informacion sensible y acciones reales.
                </p>
              </div>

              <div className="grid gap-6 lg:grid-cols-3">
                {securityItems.map((item) => (
                  <SecurityCard
                    key={item.title}
                    description={item.description}
                    title={item.title}
                  />
                ))}
              </div>
            </div>
          </section>

        </main>

        <footer className="border-t border-[color:var(--landing-border)] bg-[color:var(--landing-surface)] px-6 py-8 lg:px-8">
          <div className="mx-auto flex w-full max-w-7xl flex-col items-center justify-between gap-4 text-center md:flex-row md:text-left">
            <p className="text-base text-[var(--landing-muted)]">
              &copy; {currentYear} {BRAND_NAME}
            </p>

            <div className="flex flex-wrap items-center justify-center gap-6 text-base text-[var(--landing-muted)] md:justify-end">
              <a
                href="mailto:legal@activa.ai?subject=Privacidad"
                className="transition-colors hover:text-[var(--landing-accent)]"
              >
                Privacidad
              </a>
              <a
                href="mailto:legal@activa.ai?subject=Terminos"
                className="transition-colors hover:text-[var(--landing-accent)]"
              >
                Terminos
              </a>
              <a
                href="mailto:contact@activa.ai"
                className="transition-colors hover:text-[var(--landing-accent)]"
              >
                Contacto
              </a>
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
}
