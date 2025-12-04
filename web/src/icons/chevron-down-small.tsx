import { IconProps } from "@/icons";

const SvgChevronDownSmall = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M5 6.50001L7.5286 9.0286C7.78894 9.28893 8.21107 9.28893 8.47141 9.0286L11 6.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgChevronDownSmall;
