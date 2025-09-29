import * as React from "react";

type IconProps = React.SVGProps<SVGSVGElement> & {
  /** Convenience prop to set both width & height */
  size?: number | string;
  /** Optional accessible title */
  title?: string;
  /** Stroke color override (defaults to currentColor) */
  color?: string;
};

export const MultipleFilesIcon = React.forwardRef<SVGSVGElement, IconProps>(
  ({ size = 16, color = "currentColor", title, className, ...props }, ref) => (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 16 14"
      width={size}
      height={size}
      fill="none"
      role={title ? "img" : "presentation"}
      aria-label={title}
      className={className}
      {...props}
    >
      {title ? <title>{title}</title> : null}
      <path
        d="M5.5 0.999903H2.33334C1.97971 0.999903 1.64058 1.14038 1.39053 1.39043C1.14048 1.64048 1 1.97961 1 2.33324L1 11.6666C1 12.0202 1.14048 12.3593 1.39052 12.6094C1.64057 12.8594 1.97971 12.9999 2.33333 12.9999L8.33 12.9999C8.68362 12.9999 9.02276 12.8594 9.27281 12.6094C9.52286 12.3593 9.66333 12.0202 9.66333 11.6666L9.66334 5.1699M5.5 0.999903L9.66334 5.1699M5.5 0.999903V5.1699H9.66334M9.16167 0.999878L11.7475 3.58578C12.1226 3.96085 12.3333 4.46956 12.3333 4.99999V11.3332C12.3333 11.9076 12.2107 12.5182 11.9459 13.0032M14.6126 13.0033C14.8773 12.5182 15 11.9077 15 11.3333L15 5.24415C15 3.91915 14.4741 2.64833 13.5377 1.71083L12.8268 0.999909"
        stroke={color}
        strokeOpacity={1}
        strokeWidth={1.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
);

MultipleFilesIcon.displayName = "MultipleFilesIcon";

export const OpenFolderIcon = React.forwardRef<SVGSVGElement, IconProps>(
  ({ size = 32, color = "currentColor", title, className, ...props }, ref) => (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 32 26"
      width={size}
      height={size}
      fill="none"
      role={title ? "img" : "presentation"}
      aria-label={title}
      className={className}
      {...props}
    >
      {title ? <title>{title}</title> : null}
      <path
        d="M30.4177 15.4931L29.1847 15.2876L30.4177 15.4931ZM29.4177 21.4932L30.6507 21.6987V21.6987L29.4177 21.4932ZM2.58209 21.4932L1.3491 21.6987L2.58209 21.4932ZM1.58209 15.4931L0.349095 15.6986L1.58209 15.4931ZM13.8786 2.87868L12.9947 3.76256V3.76256L13.8786 2.87868ZM16.1212 5.12132L17.0051 4.23744V4.23744L16.1212 5.12132ZM4.54127 11.9999V13.2499H27.4585V11.9999V10.7499H4.54127V11.9999ZM30.4177 15.4931L29.1847 15.2876L28.1847 21.2877L29.4177 21.4932L30.6507 21.6987L31.6507 15.6986L30.4177 15.4931ZM26.4585 24V22.75H5.54128V24V25.25H26.4585V24ZM2.58209 21.4932L3.81509 21.2877L2.81508 15.2876L1.58209 15.4931L0.349095 15.6986L1.3491 21.6987L2.58209 21.4932ZM5.54128 24V22.75C4.68581 22.75 3.95572 22.1315 3.81509 21.2877L2.58209 21.4932L1.3491 21.6987C1.69065 23.748 3.46371 25.25 5.54128 25.25V24ZM29.4177 21.4932L28.1847 21.2877C28.0441 22.1315 27.314 22.75 26.4585 22.75V24V25.25C28.5361 25.25 30.3091 23.748 30.6507 21.6987L29.4177 21.4932ZM18.2425 6V7.25H25.9999V6V4.75H18.2425V6ZM5.9999 2V3.25H11.7573V2V0.75H5.9999V2ZM13.8786 2.87868L12.9947 3.76256L15.2373 6.0052L16.1212 5.12132L17.0051 4.23744L14.7625 1.9948L13.8786 2.87868ZM11.7573 2V3.25C12.2214 3.25 12.6665 3.43437 12.9947 3.76256L13.8786 2.87868L14.7625 1.9948C13.9654 1.19777 12.8844 0.75 11.7573 0.75V2ZM18.2425 6V4.75C17.7784 4.75 17.3333 4.56563 17.0051 4.23744L16.1212 5.12132L15.2373 6.0052C16.0344 6.80223 17.1154 7.25 18.2425 7.25V6ZM28.9999 9H30.2499C30.2499 6.65279 28.3471 4.75 25.9999 4.75V6V7.25C26.9664 7.25 27.7499 8.0335 27.7499 9H28.9999ZM2.99989 5H4.24989C4.24989 4.0335 5.0334 3.25 5.9999 3.25V2V0.75C3.65269 0.75 1.74989 2.65279 1.74989 5H2.99989ZM28.9999 9H27.7499V12.4249H28.9999H30.2499V9H28.9999ZM27.4585 11.9999V13.2499C27.7932 13.2499 28.0975 13.3411 28.3564 13.4965L28.9999 12.4249L29.6434 11.3533C29.0065 10.9708 28.2589 10.7499 27.4585 10.7499V11.9999ZM28.9999 12.4249L28.3564 13.4965C28.9538 13.8553 29.3076 14.5505 29.1847 15.2876L30.4177 15.4931L31.6507 15.6986C31.9508 13.8982 31.0763 12.2138 29.6434 11.3533L28.9999 12.4249ZM2.99989 12.4249H4.24989V5H2.99989H1.74989V12.4249H2.99989ZM4.54127 11.9999V10.7499C3.74089 10.7499 2.99329 10.9708 2.35636 11.3533L2.99989 12.4249L3.64343 13.4965C3.90228 13.3411 4.20658 13.2499 4.54127 13.2499V11.9999ZM2.99989 12.4249L2.35636 11.3533C0.923529 12.2138 0.0490297 13.8982 0.349095 15.6986L1.58209 15.4931L2.81508 15.2876C2.69222 14.5505 3.04602 13.8553 3.64343 13.4965L2.99989 12.4249Z"
        fill={color}
        fillOpacity={0.8}
        stroke={color}
        strokeOpacity={0.8}
        strokeWidth={0.2}
      />
    </svg>
  )
);

OpenFolderIcon.displayName = "OpenFolderIcon";

export const ListSettingsIcon = React.forwardRef<SVGSVGElement, IconProps>(
  ({ size = 14, color = "currentColor", title, className, ...props }, ref) => (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 14 14"
      width={size}
      height={size}
      fill="none"
      role={title ? "img" : "presentation"}
      aria-label={title}
      className={className}
      {...props}
    >
      {title ? <title>{title}</title> : null}
      <path
        d="M13 4H1M13 1H1M5 10H1M10.5 7.5V10M10.5 10V12.5M10.5 10H8M10.5 10H13M7.5 7H1"
        stroke={color}
        strokeOpacity={0.8}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
);

ListSettingsIcon.displayName = "ListSettingsIcon";

export const ChatBubbleIcon = React.forwardRef<SVGSVGElement, IconProps>(
  ({ size = 16, color = "currentColor", title, className, ...props }, ref) => (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 16 16"
      width={size}
      height={size}
      fill="none"
      role={title ? "img" : "presentation"}
      aria-label={title}
      className={className}
      {...props}
    >
      {title ? <title>{title}</title> : null}
      <path
        d="M10.4939 6.5H5.5M8.00607 9.5H5.50607M1.5 13.5H10.5C12.7091 13.5 14.5 11.7091 14.5 9.5V6.5C14.5 4.29086 12.7091 2.5 10.5 2.5H5.5C3.29086 2.5 1.5 4.29086 1.5 6.5V13.5Z"
        stroke={color}
        strokeOpacity={0.6}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
);

ChatBubbleIcon.displayName = "ChatBubbleIcon";

export const DocumentIcon = React.forwardRef<SVGSVGElement, IconProps>(
  ({ size = 20, color = "currentColor", title, className, ...props }, ref) => (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 20 20"
      width={size}
      height={size}
      fill="none"
      role={title ? "img" : "presentation"}
      aria-label={title}
      className={className}
      {...props}
    >
      {title ? <title>{title}</title> : null}
      <path
        d="M11.6668 1.66669H5.00016C4.55814 1.66669 4.13421 1.84228 3.82165 2.15484C3.50909 2.4674 3.3335 2.89133 3.3335 3.33335V16.6667C3.3335 17.1087 3.50909 17.5326 3.82165 17.8452C4.13421 18.1578 4.55814 18.3334 5.00016 18.3334H15.0002C15.4422 18.3334 15.8661 18.1578 16.1787 17.8452C16.4912 17.5326 16.6668 17.1087 16.6668 16.6667V6.66669M11.6668 1.66669L16.6668 6.66669M11.6668 1.66669L11.6668 6.66669L16.6668 6.66669M13.3335 10.8334H6.66683M13.3335 14.1667H6.66683M8.3335 7.50002H6.66683"
        stroke={color}
        strokeOpacity={1}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
);

DocumentIcon.displayName = "DocumentIcon";

export const OpenInNewIcon = React.forwardRef<SVGSVGElement, IconProps>(
  ({ size = 14, color = "currentColor", title, className, ...props }, ref) => (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 14 14"
      width={size}
      height={size}
      fill="none"
      role={title ? "img" : "presentation"}
      aria-label={title}
      className={className}
      {...props}
    >
      {title ? <title>{title}</title> : null}
      <path
        d="M11 7.66667V11.6667C11 12.0203 10.8595 12.3594 10.6095 12.6095C10.3594 12.8595 10.0203 13 9.66667 13H2.33333C1.97971 13 1.64057 12.8595 1.39052 12.6095C1.14048 12.3594 1 12.0203 1 11.6667V4.33333C1 3.97971 1.14048 3.64057 1.39052 3.39052C1.64057 3.14048 1.97971 3 2.33333 3H6.33333M9 1H13M13 1V5M13 1L5.66667 8.33333"
        stroke={color}
        strokeOpacity={1}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
);

OpenInNewIcon.displayName = "OpenInNewIcon";
