import type { Route } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const BRAND_NAME = "ACTIVA";
const BRAND_DESCRIPTOR = "IA operativa";
const BRAND_PROMISE = "Menos busqueda. Mas ejecucion.";
const BRAND_TAGLINE = "De la informacion a la accion.";
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

interface StepCardProps extends Step {}

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
  { href: "#contacto", label: "Contacto" },
];

const features: Feature[] = [
  {
    index: "01",
    title: "Chat con fuentes",
    description:
      "Responde con evidencia interna, citas verificables y contexto conectado a documentos, tableros y conocimiento operativo.",
  },
  {
    index: "02",
    title: "Acciones operativas",
    description:
      "Activa pasos sobre bases de datos, servicios y flujos internos con confirmacion, permisos y control.",
  },
  {
    index: "03",
    title: "Permisos y auditoria",
    description:
      "Cada accion queda registrada con respaldo suficiente para revisar, aprobar o rastrear decisiones.",
  },
  {
    index: "04",
    title: "Conectores empresariales",
    description:
      "Integra PostgreSQL, Google Drive, Notion, Slack y APIs propias sin romper la operacion del equipo.",
  },
];

const steps: Step[] = [
  {
    number: "01",
    title: "Conecta tu contexto",
    description:
      "Centraliza documentos, datos y herramientas para que ACTIVA pueda trabajar sobre informacion real.",
  },
  {
    number: "02",
    title: "Consulta con evidencia",
    description:
      "Obtiene respuestas claras con fuentes verificables para entender que esta pasando y por que.",
  },
  {
    number: "03",
    title: "Ejecuta con control",
    description:
      "Convierte la respuesta en una accion concreta con aprobacion, permisos y trazabilidad completa.",
  },
];

const securityItems: SecurityItem[] = [
  {
    title: "Respuestas con respaldo",
    description:
      "Las respuestas se apoyan en evidencia interna y no en texto suelto sin contexto.",
  },
  {
    title: "Acciones con permiso",
    description:
      "La experiencia permite validar, aprobar y limitar acciones antes de afectar sistemas reales.",
  },
  {
    title: "Registro completo",
    description:
      "Cada paso puede quedar auditado para que el equipo sepa que se hizo, cuando y con que fuente.",
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
        "inline-flex min-h-11 items-center justify-center rounded-full px-6 py-3 text-sm font-semibold transition-all duration-300",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-theme-orange-04 focus-visible:ring-offset-2",
        "hover:-translate-y-0.5",
        variant === "primary"
          ? "bg-theme-orange-04 text-activa-ink-100 shadow-01 hover:bg-theme-orange-05"
          : "border border-theme-orange-02 bg-background-neutral-00 text-theme-orange-05 hover:bg-theme-orange-01",
        className
      )}
    >
      {children}
    </Link>
  );
}

function FeatureCard({ description, index, title }: FeatureCardProps) {
  return (
    <article className="rounded-16 border border-border-01 bg-background-neutral-00 p-7 shadow-01">
      <div className="inline-flex rounded-full bg-theme-orange-01 px-3 py-1">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-theme-orange-05">
          {index}
        </p>
      </div>
      <h3 className="pt-4 text-[1.45rem] font-semibold tracking-[-0.04em] text-text-05">
        {title}
      </h3>
      <p className="pt-3 text-base leading-7 text-text-03">{description}</p>
    </article>
  );
}

function StepCard({ description, number, title }: StepCardProps) {
  return (
    <article className="rounded-16 border border-border-01 bg-background-neutral-00 p-7 shadow-01">
      <div className="inline-flex rounded-full bg-theme-amber-01 px-3 py-1">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-theme-amber-05">
          {number}
        </p>
      </div>
      <h3 className="pt-4 text-[1.4rem] font-semibold tracking-[-0.04em] text-text-05">
        {title}
      </h3>
      <p className="pt-3 text-base leading-7 text-text-03">{description}</p>
    </article>
  );
}

function SecurityCard({ description, title }: SecurityCardProps) {
  return (
    <article className="rounded-16 border border-theme-orange-02 bg-theme-orange-01 p-7">
      <h3 className="text-[1.35rem] font-semibold tracking-[-0.04em] text-text-05">
        {title}
      </h3>
      <p className="pt-3 text-base leading-7 text-text-03">{description}</p>
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
    <div className="min-h-screen bg-background-neutral-00 text-text-05">
      <div className="relative overflow-hidden">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-0 h-[34rem] bg-[radial-gradient(circle_at_top,_var(--theme-orange-01),_transparent_68%)]"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute left-1/2 top-20 h-[24rem] w-[24rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,_var(--theme-amber-01),_transparent_72%)]"
        />

        <header className="sticky top-0 z-40 border-b border-theme-orange-02 bg-background-neutral-00/95 backdrop-blur-md">
          <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-6 py-4 lg:px-8">
            <Link href="/" className="flex items-center gap-3 text-text-05">
              <span className="flex h-11 w-11 items-center justify-center rounded-12 bg-theme-orange-04 text-sm font-semibold tracking-[0.12em] text-activa-ink-100">
                A
              </span>
              <span className="flex flex-col">
                <span className="text-2xl font-semibold tracking-[-0.08em]">
                  {BRAND_NAME}
                </span>
                <span className="hidden text-xs uppercase tracking-[0.24em] text-text-03 md:block">
                  {BRAND_DESCRIPTOR}
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
                  className="text-base font-medium text-text-03 transition-colors hover:text-theme-orange-05"
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

        <main>
          <section className="relative px-6 py-20 lg:px-8 lg:py-24">
            <div className="mx-auto grid w-full max-w-7xl gap-14 lg:grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)] lg:items-center">
              <div className="max-w-3xl">
                <div className="inline-flex items-center rounded-full border border-theme-orange-02 bg-theme-orange-01 px-4 py-2 text-sm font-medium text-theme-orange-05 shadow-01">
                  {BRAND_PROMISE}
                </div>

                <div className="pt-8 text-xs font-semibold uppercase tracking-[0.28em] text-text-03">
                  {BRAND_NAME} / {BRAND_DESCRIPTOR}
                </div>

                <h1 className="pt-6 text-[clamp(3.1rem,7vw,5.9rem)] font-semibold leading-[0.94] tracking-[-0.07em] text-text-05">
                  Tu copiloto operativo
                  <br />
                  para trabajar con claridad
                </h1>

                <p className="max-w-2xl pt-6 text-[clamp(1.05rem,2vw,1.35rem)] leading-[1.75] text-text-03">
                  ACTIVA une evidencia, decisiones y ejecucion en una sola
                  experiencia. Consulta informacion interna, entiende lo que
                  esta pasando y convierte la respuesta en una accion concreta
                  sin salir del flujo.
                </p>

                <p className="max-w-2xl pt-5 text-base leading-7 text-text-03">
                  Pensada para equipos que trabajan con documentos, bases de
                  datos, conectores y procesos reales. Menos cambio de
                  contexto, menos friccion y mas capacidad para operar con
                  criterio.
                </p>

                <div className="flex flex-wrap items-center gap-4 pt-10">
                  <LandingButton href={REGISTER_ROUTE} className="px-8 py-3">
                    Crear cuenta gratis
                  </LandingButton>
                  <LandingButton
                    href={LOGIN_ROUTE}
                    variant="secondary"
                    className="px-8 py-3"
                  >
                    Iniciar sesion
                  </LandingButton>
                </div>

                <p className="pt-8 text-sm font-semibold uppercase tracking-[0.24em] text-text-03">
                  {BRAND_TAGLINE}
                </p>
              </div>

              <div className="w-full max-w-[36rem] justify-self-end">
                <div className="rounded-16 border border-border-01 bg-background-neutral-00 p-5 shadow-02">
                  <div className="rounded-16 bg-[linear-gradient(180deg,var(--theme-orange-01)_0%,var(--background-neutral-00)_100%)] p-5">
                    <p className="text-xs font-semibold uppercase tracking-[0.24em] text-text-03">
                      Vista operativa
                    </p>
                    <h2 className="pt-4 text-[1.75rem] font-semibold leading-[1.12] tracking-[-0.05em] text-text-05">
                      Mas contexto. Menos friccion.
                    </h2>

                    <div className="pt-5">
                      <div className="rounded-12 border border-border-01 bg-background-neutral-00 p-4">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-text-03">
                          Consulta
                        </p>
                        <p className="pt-2 text-sm leading-6 text-text-03">
                          Resume la cartera vencida y recomienda el siguiente
                          paso operativo con respaldo en fuentes internas.
                        </p>
                      </div>
                    </div>

                    <div className="pt-4">
                      <div className="rounded-12 border border-theme-orange-02 bg-theme-amber-01 p-5">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-theme-orange-05">
                          Respuesta
                        </p>
                        <p className="pt-3 text-base leading-7 text-activa-ink-100">
                          Se detectaron 14 cuentas criticas. La recomendacion es
                          iniciar recordatorio con aprobacion y dejar la
                          evidencia ligada a las fuentes consultadas.
                        </p>
                      </div>
                    </div>

                    <div className="grid gap-3 pt-4 sm:grid-cols-3">
                      <div className="rounded-12 border border-border-01 bg-background-neutral-00 p-4">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-text-03">
                          Fuentes
                        </p>
                        <p className="pt-2 text-sm font-semibold text-text-05">
                          3 verificadas
                        </p>
                      </div>
                      <div className="rounded-12 border border-border-01 bg-background-neutral-00 p-4">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-text-03">
                          Accion
                        </p>
                        <p className="pt-2 text-sm font-semibold text-text-05">
                          Lista para aprobar
                        </p>
                      </div>
                      <div className="rounded-12 border border-border-01 bg-background-neutral-00 p-4">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-text-03">
                          Auditoria
                        </p>
                        <p className="pt-2 text-sm font-semibold text-text-05">
                          Completa
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="border-y border-theme-orange-02 bg-background-neutral-00 px-6 py-6 lg:px-8">
            <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center gap-3">
              <span className="rounded-full border border-theme-orange-02 bg-theme-orange-01 px-4 py-2 text-sm font-medium text-theme-orange-05">
                PostgreSQL
              </span>
              <span className="rounded-full border border-theme-orange-02 bg-theme-orange-01 px-4 py-2 text-sm font-medium text-theme-orange-05">
                Google Drive
              </span>
              <span className="rounded-full border border-theme-orange-02 bg-theme-orange-01 px-4 py-2 text-sm font-medium text-theme-orange-05">
                Notion
              </span>
              <span className="rounded-full border border-theme-orange-02 bg-theme-orange-01 px-4 py-2 text-sm font-medium text-theme-orange-05">
                Slack
              </span>
              <span className="rounded-full border border-theme-orange-02 bg-theme-orange-01 px-4 py-2 text-sm font-medium text-theme-orange-05">
                APIs internas
              </span>
            </div>
          </section>

          <section className="relative bg-background-neutral-00 px-6 py-20 lg:px-8">
            <SectionAnchor id="producto" />

            <div className="mx-auto w-full max-w-7xl">
              <div className="max-w-2xl pb-12">
                <p className="text-xs font-semibold uppercase tracking-[0.26em] text-text-03">
                  Producto
                </p>
                <h2 className="pt-4 text-[clamp(2.2rem,4vw,3.6rem)] font-semibold leading-[1.04] tracking-[-0.06em] text-text-05">
                  Mas texto util. Menos interfaz vacia.
                </h2>
                <p className="pt-5 text-lg leading-8 text-text-03">
                  ACTIVA no esta pensada para verse solamente limpia. Esta
                  pensada para explicar bien lo que hace, por que importa y como
                  encaja en una operacion real.
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

          <section className="relative border-t border-theme-orange-02 bg-background-tint-01 px-6 py-20 lg:px-8">
            <SectionAnchor id="flujo" />

            <div className="mx-auto grid w-full max-w-7xl gap-10 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
              <div className="max-w-2xl">
                <p className="text-xs font-semibold uppercase tracking-[0.26em] text-text-03">
                  Como funciona
                </p>
                <h2 className="pt-4 text-[clamp(2.2rem,4vw,3.5rem)] font-semibold leading-[1.04] tracking-[-0.06em] text-text-05">
                  De la consulta a la ejecucion en tres pasos.
                </h2>
                <p className="pt-5 text-lg leading-8 text-text-03">
                  La experiencia completa busca reducir el salto entre entender
                  algo y actuar sobre ello. Menos herramientas separadas, mas
                  continuidad dentro del mismo flujo.
                </p>
              </div>

              <div className="grid gap-6">
                {steps.map((step) => (
                  <StepCard
                    key={step.number}
                    description={step.description}
                    number={step.number}
                    title={step.title}
                  />
                ))}
              </div>
            </div>
          </section>

          <section className="relative border-t border-theme-orange-02 bg-background-neutral-00 px-6 py-20 lg:px-8">
            <SectionAnchor id="seguridad" />

            <div className="mx-auto w-full max-w-7xl">
              <div className="max-w-2xl pb-12">
                <p className="text-xs font-semibold uppercase tracking-[0.26em] text-text-03">
                  Seguridad
                </p>
                <h2 className="pt-4 text-[clamp(2.2rem,4vw,3.5rem)] font-semibold leading-[1.04] tracking-[-0.06em] text-text-05">
                  Hecha para operar con respaldo.
                </h2>
                <p className="pt-5 text-lg leading-8 text-text-03">
                  La propuesta no es solo responder mejor. Es hacerlo con el
                  nivel de control que un equipo necesita cuando trabaja con
                  informacion sensible y acciones reales.
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

          <section className="relative border-t border-theme-orange-02 bg-background-tint-01 px-6 py-20 lg:px-8">
            <SectionAnchor id="contacto" />

            <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 rounded-16 border border-theme-orange-02 bg-theme-orange-01 p-8 shadow-01 lg:flex-row lg:items-end lg:justify-between lg:p-12">
              <div className="max-w-3xl">
                <p className="text-xs font-semibold uppercase tracking-[0.26em] text-text-03">
                  {BRAND_NAME}
                </p>
                <h2 className="pt-4 text-[clamp(2.3rem,4vw,3.7rem)] font-semibold leading-[1.04] tracking-[-0.06em] text-text-05">
                  Moderna, clara y lista para usarse.
                </h2>
                <p className="pt-5 text-lg leading-8 text-text-03">
                  Crea tu cuenta, conecta tus fuentes y lleva la operacion desde
                  la informacion hasta la accion sin complicaciones.
                </p>
              </div>

              <div className="flex flex-wrap gap-4">
                <LandingButton href={REGISTER_ROUTE} className="px-8 py-4">
                  Comenzar gratis
                </LandingButton>
                <LandingButton
                  href={LOGIN_ROUTE}
                  variant="secondary"
                  className="px-8 py-4"
                >
                  Iniciar sesion
                </LandingButton>
              </div>
            </div>
          </section>
        </main>

        <footer className="border-t border-theme-orange-02 bg-background-neutral-00 px-6 py-8 lg:px-8">
          <div className="mx-auto flex w-full max-w-7xl flex-col items-center justify-between gap-4 text-center md:flex-row md:text-left">
            <p className="text-base text-text-03">
              &copy; {currentYear} {BRAND_NAME}
            </p>

            <div className="flex flex-wrap items-center justify-center gap-6 text-base text-text-03 md:justify-end">
              <a
                href="mailto:legal@activa.ai?subject=Privacidad"
                className="transition-colors hover:text-theme-orange-05"
              >
                Privacidad
              </a>
              <a
                href="mailto:legal@activa.ai?subject=Terminos"
                className="transition-colors hover:text-theme-orange-05"
              >
                Terminos
              </a>
              <a
                href="mailto:contact@activa.ai"
                className="transition-colors hover:text-theme-orange-05"
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
