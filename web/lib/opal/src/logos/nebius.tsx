import type { IconProps } from "@opal/types";

// Nebius Token Factory mark — the lime rounded-square-with-plus glyph on the
// brand's dark tile (its official lockup). The dark tile keeps the light lime
// mark visible on light provider-card backgrounds, where a bare lime glyph
// washes out. Colors are inlined (like the other brand logos) rather than a
// Tailwind text-color class, so the mark renders regardless of theme.
const SvgNebius = ({ size, className, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 28 28"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    {...props}
  >
    <title>Nebius TokenFactory</title>
    <rect width="28" height="28" rx="6.5" fill="#0B0B0B" />
    <path
      transform="translate(4.2 4.2) scale(0.7) translate(-103 0)"
      d="M124.041 0c3.842 0 6.958 3.16 6.958 7.06v13.88l-.009.364c-.186 3.73-3.226 6.696-6.949 6.696h-14.083l-.357-.01c-3.558-.183-6.412-3.077-6.592-6.686L103 20.94V7.06c0-3.9 3.115-7.06 6.958-7.06h14.083Zm-14.083.916c-3.324 0-6.042 2.738-6.042 6.144v13.88c0 3.405 2.718 6.144 6.042 6.144h14.083c3.324 0 6.042-2.738 6.042-6.144V7.06c0-3.3-2.551-5.971-5.732-6.135l-.31-.009h-14.083Zm5.244 4.78c.301 0 .544.244.544.544V8.63c0 .214.173.389.388.389h2.389c.301 0 .544.243.544.544v2.388a.39.39 0 0 0 .389.389h2.389c.301 0 .545.244.545.545v2.233a.546.546 0 0 1-.545.544h-2.389a.39.39 0 0 0-.389.389v2.389c0 .3-.243.543-.544.543h-2.389a.389.389 0 0 0-.388.39v2.388c0 .3-.243.543-.544.544h-2.233a.543.543 0 0 1-.544-.544v-2.234c0-.3.243-.544.544-.544h2.388a.389.389 0 0 0 .389-.388v-2.389c0-.3.243-.544.544-.544h2.39a.388.388 0 0 0 .387-.388v-2.544a.389.389 0 0 0-.387-.39h-2.39a.543.543 0 0 1-.544-.544V9.406a.389.389 0 0 0-.389-.388h-2.388a.543.543 0 0 1-.544-.544V6.24c0-.3.243-.544.544-.544h2.233Z"
      fill="#E0FF4F"
    />
  </svg>
);

export default SvgNebius;
