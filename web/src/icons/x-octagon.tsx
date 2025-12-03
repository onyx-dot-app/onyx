import { IconProps } from "@/icons";

const SvgXOctagon = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 15 15"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M9.41667 5.41667L5.41667 9.41667M5.41667 5.41667L9.41667 9.41667M4.65667 0.75H10.1767L14.0833 4.65667V10.1767L10.1767 14.0833H4.65667L0.75 10.1767V4.65667L4.65667 0.75Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgXOctagon;
