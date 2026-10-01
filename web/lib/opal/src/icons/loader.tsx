import type { IconProps } from "@opal/types";

const SvgLoader = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    {/* The track: a faint full ring the arc travels along. */}
    <circle cx="8" cy="8" r="6.66667" strokeWidth={1.5} strokeOpacity={0.25} />
    {/* The arc: the solid head that shows the spin. */}
    <path
      d="M8.00003 1.33333C9.84098 1.33333 11.5076 2.07952 12.7141 3.28595"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgLoader;
