import type { IconProps } from "@opal/types";
const SvgEmpty = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 120 120"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M18.75 71.25V90C18.75 94.1421 22.1079 97.5 26.25 97.5H93.75C97.8921 97.5 101.25 94.1422 101.25 90V71.25H18.75Z"
      fill="#E6E6E6"
    />
    <path d="M18.75 71.25H101.25L86.25 48.75H33.75L18.75 71.25Z" fill="white" />
    <path
      d="M18.75 71.25V90C18.75 94.1421 22.1079 97.5 26.25 97.5H93.75C97.8921 97.5 101.25 94.1422 101.25 90V71.25M18.75 71.25H101.25M18.75 71.25L33.75 48.75H86.25L101.25 71.25M54.375 80.625H65.625"
      stroke="#A4A4A4"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M43.125 35.625L33.75 26.25M76.875 35.625L86.25 26.25M60 28.125V15"
      stroke="#FFC733"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgEmpty;
