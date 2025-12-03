import { IconProps } from "@/icons";

const SvgEye = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 12"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M1 6.00088C1 6.00088 3.54545 0.909973 8 0.909973C12.4545 0.909973 15 6.00088 15 6.00088C15 6.00088 12.4545 11.0918 8 11.0918C3.54545 11.0918 1 6.00088 1 6.00088Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M8 7.90997C9.05436 7.90997 9.90909 7.05524 9.90909 6.00088C9.90909 4.94652 9.05436 4.09179 8 4.09179C6.94564 4.09179 6.09091 4.94652 6.09091 6.00088C6.09091 7.05524 6.94564 7.90997 8 7.90997Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgEye;
