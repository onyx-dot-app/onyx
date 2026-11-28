import type { IconProps } from "@opal/types";
const SvgEye = ({ size, ...props }: IconProps) => (
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
      d="M1 8.00082C1 8.00082 3.54545 2.90991 8 2.90991C12.4545 2.90991 15 8.00082 15 8.00082C15 8.00082 12.4545 13.0917 8 13.0917C3.54545 13.0917 1 8.00082 1 8.00082ZM9.90909 8.00082C9.90909 9.05518 9.05436 9.90991 8 9.90991C6.94564 9.90991 6.09091 9.05518 6.09091 8.00082C6.09091 6.94646 6.94564 6.09173 8 6.09173C9.05436 6.09173 9.90909 6.94646 9.90909 8.00082Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgEye;
