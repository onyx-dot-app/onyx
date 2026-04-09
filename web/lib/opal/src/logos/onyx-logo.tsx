import type { IconProps } from "@opal/types";
const SvgOnyxLogo = ({ size, ...props }: IconProps) => (
  <svg
    height={size}
    viewBox="0 0 64 64"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M10.4014 13.25L18.875 32L10.3852 50.75L2 32L10.4014 13.25Z"
      fill="var(--theme-primary-05)"
    />
    <path
      d="M53.5264 13.25L62 32L53.5102 50.75L45.125 32L53.5264 13.25Z"
      fill="var(--theme-primary-05)"
    />
    <path
      d="M32 45.125L50.75 53.5625L32 62L13.25 53.5625L32 45.125Z"
      fill="var(--theme-primary-05)"
    />
    <path
      d="M32 2L50.75 10.4375L32 18.875L13.25 10.4375L32 2Z"
      fill="var(--theme-primary-05)"
    />
  </svg>
);
export default SvgOnyxLogo;
