import type { IconProps } from "@opal/types";
const SvgSearchSmall = ({ size, ...props }: IconProps) => (
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
      d="M9.69454 9.69454C10.7685 8.6206 10.7685 6.8794 9.69454 5.80546C8.6206 4.73151 6.8794 4.73151 5.80546 5.80546C4.73151 6.8794 4.73151 8.6206 5.80546 9.69454C6.8794 10.7685 8.6206 10.7685 9.69454 9.69454ZM9.69454 9.69454L11 11"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgSearchSmall;
