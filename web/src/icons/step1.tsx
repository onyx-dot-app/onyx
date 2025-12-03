import { IconProps } from "@/icons";

const SvgStep1 = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 15 15"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M7.41989 7.42018L11.7505 4.92023C10.8858 3.42605 9.27082 2.42116 7.42035 2.42106L7.41989 7.42018Z"
      fill="currentColor"
    />
    <path
      fillRule="evenodd"
      clipRule="evenodd"
      d="M7.4198 7.42V2.42C9.14596 2.42161 10.8242 3.31822 11.7494 4.92083L7.4198 7.42Z"
      fill="currentColor"
    />
    <path
      d="M7.41667 14.0833C11.0986 14.0833 14.0833 11.0986 14.0833 7.41667C14.0833 3.73477 11.0986 0.75 7.41667 0.75C3.73477 0.75 0.75 3.73477 0.75 7.41667C0.75 11.0986 3.73477 14.0833 7.41667 14.0833Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgStep1;
