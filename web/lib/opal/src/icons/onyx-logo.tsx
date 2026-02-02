import type { IconProps } from "@opal/types";

const SvgOnyxLogo = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 56 56"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      fillRule="evenodd"
      clipRule="evenodd"
      d="M28 0 10.869 7.77 28 15.539l17.131-7.77L28 0Zm0 40.461-17.131 7.77L28 56l17.131-7.77L28 40.461Zm20.231-29.592L56 28.001l-7.769 17.131L40.462 28l7.769-17.131ZM15.538 28 7.77 10.869 0 28l7.769 17.131L15.538 28Z"
      fill="currentColor"
    />
  </svg>
);
export default SvgOnyxLogo;
