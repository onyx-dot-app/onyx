import type { IconProps } from "@opal/types";

const SvgPaintBrush = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 32 32"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M5.00001 17L5.00002 19.2344C5.00003 20.2431 5.7511 21.0939 6.75195 21.219L11.2481 21.781C12.2489 21.9061 13 22.7569 13 23.7656L13 26C13 27.6569 14.3431 29 16 29C17.6569 29 19 27.6569 19 26L19 23.7656C19 22.7569 19.7511 21.9061 20.7519 21.781L25.2481 21.219C26.2489 21.0939 27 20.2431 27 19.2344L27 17M5.00001 17L5 9C5 5.68629 7.68629 3 11 3H17M5.00001 17H27M27 17L27 3H22M22 3L22 10M22 3H17M17 3L17 8"
      strokeWidth={2.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgPaintBrush;
