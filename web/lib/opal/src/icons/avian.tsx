import type { IconProps } from "@opal/types";

const SvgAvian = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 48 48"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <title>Avian</title>
    <path
      d="M6 38C10 34 16 28 22 24C16 22 10 18 6 14C12 16 20 18 26 20C22 16 18 10 16 4C20 10 26 16 30 20C30 14 32 8 36 2C34 10 34 18 34 24C38 22 42 20 46 20C42 22 38 26 34 28C36 32 38 36 42 40C38 38 34 34 30 32C28 36 24 40 20 42C24 38 26 34 28 30C22 32 14 36 6 38Z"
      fill="currentColor"
    />
  </svg>
);

export default SvgAvian;
