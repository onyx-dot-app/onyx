import Link from "next/link";
import type { Route } from "next";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const BRAND_NAME = "ACTIVA";
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
  icon: ReactNode;
  title: string;
}

interface FeatureCardProps {
  description: string;
  icon: ReactNode;
  title: string;
}

interface FeatureAnchorProps {
  id: string;
}

interface IconProps {
  className?: string;
}

const navItems: NavItem[] = [
  { href: "#product", label: "Product" },
  { href: "#security", label: "Security" },
  { href: "#pricing", label: "Pricing" },
  { href: "#docs", label: "Docs" },
];

const features: Feature[] = [
  {
    icon: <MessageIcon className="h-5 w-5" />,
    title: "Chat + Fuentes",
    description:
      "Respuestas basadas en tus documentos internos con citas verificables y trazabilidad completa.",
  },
  {
    icon: <LightningIcon className="h-5 w-5" />,
    title: "Acciones operativas",
    description:
      "Ejecuta operaciones sobre bases de datos y servicios con previsualizaci\u00f3n y confirmaci\u00f3n.",
  },
  {
    icon: <ShieldIcon className="h-5 w-5" />,
    title: "Permisos y auditor\u00eda",
    description:
      "Control granular de roles, pol\u00edticas de seguridad y registro completo de cada acci\u00f3n.",
  },
  {
    icon: <DatabaseIcon className="h-5 w-5" />,
    title: "Conectores",
    description:
      "Integraci\u00f3n con PostgreSQL, Google Drive, Notion, Slack y APIs personalizadas.",
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
        "inline-flex min-h-12 items-center justify-center rounded-lg px-6 py-3 text-sm font-semibold transition-transform duration-200",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--grey-100)]",
        "hover:-translate-y-0.5",
        variant === "primary"
          ? "bg-[var(--grey-100)] text-[var(--grey-00)]"
          : "border border-[var(--grey-100)] bg-[var(--grey-00)] text-[var(--grey-100)]",
        className
      )}
    >
      {children}
    </Link>
  );
}

function FeatureCard({ description, icon, title }: FeatureCardProps) {
  return (
    <article className="rounded-xl border border-[var(--grey-10)] bg-[var(--grey-00)] p-8 shadow-[0_12px_32px_rgba(0,0,0,0.04)]">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--grey-04)] text-[var(--grey-100)]">
        {icon}
      </div>
      <h3 className="pt-6 text-2xl font-semibold tracking-[-0.03em] text-[var(--grey-100)]">
        {title}
      </h3>
      <p className="pt-4 text-lg leading-8 text-[var(--grey-60)]">
        {description}
      </p>
    </article>
  );
}

function FeatureAnchor({ id }: FeatureAnchorProps) {
  return (
    <div
      id={id}
      aria-hidden="true"
      className="pointer-events-none absolute -top-24"
    />
  );
}

function MessageIcon({ className }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M7 18.5H6C4.067 18.5 2.5 16.933 2.5 15V7C2.5 5.067 4.067 3.5 6 3.5H18C19.933 3.5 21.5 5.067 21.5 7V15C21.5 16.933 19.933 18.5 18 18.5H11.5L7 21.5V18.5Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function LightningIcon({ className }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M13.25 2.5L4.75 13.3H11L9.75 21.5L18.25 10.7H12L13.25 2.5Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function ShieldIcon({ className }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M12 3.5C14.243 5.176 16.938 6.14 19.75 6.272V11.75C19.75 16.144 16.63 20.021 12 21.5C7.37 20.021 4.25 16.144 4.25 11.75V6.272C7.062 6.14 9.757 5.176 12 3.5Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function DatabaseIcon({ className }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <ellipse
        cx="12"
        cy="6.75"
        rx="7.25"
        ry="3.25"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path
        d="M4.75 6.75V12C4.75 13.7949 8 15.25 12 15.25C16 15.25 19.25 13.7949 19.25 12V6.75"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.8"
      />
      <path
        d="M4.75 12V17.25C4.75 19.0449 8 20.5 12 20.5C16 20.5 19.25 19.0449 19.25 17.25V12"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

export default function Landing() {
  return (
    <div className="min-h-screen bg-[var(--grey-00)] text-[var(--grey-100)]">
      <header className="sticky top-0 z-40 border-b border-[var(--grey-10)] bg-[rgba(255,255,255,0.92)] backdrop-blur-md">
        <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-6 py-4 lg:px-8">
          <Link href="/" className="flex items-center gap-3 text-[var(--grey-100)]">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--grey-100)] text-sm font-semibold tracking-[0.12em] text-[var(--grey-00)]">
              A
            </span>
            <span className="flex flex-col">
              <span className="text-2xl font-semibold tracking-[-0.08em]">
                {BRAND_NAME}
              </span>
              <span className="hidden text-xs uppercase tracking-[0.18em] text-[var(--grey-50)] md:block">
                IA operativa
              </span>
            </span>
          </Link>

          <nav
            aria-label="Main navigation"
            className="hidden items-center gap-10 md:flex"
          >
            {navItems.map((item) => (
              <a
                key={item.label}
                href={item.href}
                className="text-lg text-[var(--grey-60)] transition-colors hover:text-[var(--grey-100)]"
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
              Log In
            </LandingButton>
            <LandingButton href={REGISTER_ROUTE} className="px-4 py-2 md:px-5">
              Start Free
            </LandingButton>
          </div>
        </div>
      </header>

      <main>
        <section className="relative overflow-hidden">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 top-0 h-[30rem] bg-[radial-gradient(circle_at_top,_rgba(0,0,0,0.08),_transparent_62%)]"
          />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 top-20 mx-auto h-[28rem] max-w-5xl rounded-full border border-[rgba(0,0,0,0.04)]"
          />

          <div className="relative mx-auto flex min-h-[calc(100vh-81px)] w-full max-w-7xl flex-col items-center justify-center px-6 py-20 text-center lg:px-8">
            <div className="inline-flex items-center gap-2 rounded-full border border-[var(--grey-10)] bg-[var(--grey-04)] px-4 py-2 text-sm font-medium text-[var(--grey-70)]">
              <LightningIcon className="h-4 w-4" />
              <span>{BRAND_PROMISE}</span>
            </div>

            <div className="pt-8 text-xs font-semibold uppercase tracking-[0.28em] text-[var(--grey-50)]">
              {BRAND_NAME}
            </div>

            <h1 className="pt-8 text-[clamp(3.5rem,8vw,6rem)] font-semibold leading-[0.94] tracking-[-0.06em] text-[var(--grey-100)]">
              <span className="block">Tu copiloto operativo</span>
              <span className="block">para tu empresa</span>
            </h1>

            <p className="max-w-3xl pt-8 text-[clamp(1.125rem,2vw,1.75rem)] leading-[1.5] text-[var(--grey-60)]">
              Responde con evidencia interna. Ejecuta acciones con control y
              auditor\u00eda. Todo conectado a tus datos, con permisos y
              trazabilidad.
            </p>

            <p className="pt-4 text-base font-medium uppercase tracking-[0.18em] text-[var(--grey-50)]">
              {BRAND_TAGLINE}
            </p>

            <div className="flex flex-wrap items-center justify-center gap-4 pt-10">
              <LandingButton href={REGISTER_ROUTE} className="px-8 py-3">
                Start Free
              </LandingButton>
              <LandingButton
                href={LOGIN_ROUTE}
                variant="secondary"
                className="px-8 py-3"
              >
                Log In
              </LandingButton>
            </div>
          </div>
        </section>

        <section className="relative border-t border-[var(--grey-10)] px-6 py-24 lg:px-8">
          <FeatureAnchor id="product" />
          <FeatureAnchor id="security" />

          <div className="mx-auto grid w-full max-w-4xl gap-6 md:grid-cols-2">
            {features.map((feature) => (
              <FeatureCard
                key={feature.title}
                description={feature.description}
                icon={feature.icon}
                title={feature.title}
              />
            ))}
          </div>
        </section>

        <section className="relative border-t border-[var(--grey-10)] px-6 py-24 lg:px-8">
          <FeatureAnchor id="pricing" />

          <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
            <p className="pb-4 text-xs font-semibold uppercase tracking-[0.28em] text-[var(--grey-50)]">
              {BRAND_NAME}
            </p>
            <h2 className="text-[clamp(2.5rem,4vw,3.5rem)] font-semibold tracking-[-0.05em] text-[var(--grey-100)]">
              Listo para empezar
            </h2>
            <p className="pt-5 text-[clamp(1.125rem,2vw,1.5rem)] leading-8 text-[var(--grey-60)]">
              Configura tu workspace en minutos. Sin tarjeta de cr\u00e9dito.
            </p>
            <LandingButton href={REGISTER_ROUTE} className="mt-10 px-8 py-4">
              Crear cuenta gratis
            </LandingButton>
          </div>
        </section>
      </main>

      <footer className="border-t border-[var(--grey-10)] px-6 py-8 lg:px-8">
        <div className="mx-auto flex w-full max-w-7xl flex-col items-center justify-between gap-4 text-center md:flex-row md:text-left">
          <p className="text-base text-[var(--grey-50)]">
            &copy; 2025 {BRAND_NAME}
          </p>

          <div
            id="docs"
            className="flex flex-wrap items-center justify-center gap-6 text-base text-[var(--grey-50)] md:justify-end"
          >
            <a
              href="mailto:legal@activa.ai?subject=Privacy"
              className="transition-colors hover:text-[var(--grey-100)]"
            >
              Privacy
            </a>
            <a
              href="mailto:legal@activa.ai?subject=Terms"
              className="transition-colors hover:text-[var(--grey-100)]"
            >
              Terms
            </a>
            <a
              href="mailto:contact@activa.ai"
              className="transition-colors hover:text-[var(--grey-100)]"
            >
              Contact
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
