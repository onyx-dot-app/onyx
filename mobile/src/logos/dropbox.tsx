import Svg, { Path } from "react-native-svg";

import type { IconProps } from "@/icons/types";

const SvgDropbox = ({ size = 16, ...props }: IconProps) => (
  <Svg width={size} height={size} viewBox="0 0 52 52" fill="none" {...props}>
    <Path
      d="M13.9995 8L2 15.5375L13.9995 23.075L26.001 15.5375L38.0005 23.075L50 15.5375L38.0005 8L26.001 15.5375L13.9995 8Z"
      fill="#0061FE"
    />
    <Path
      d="M13.9995 38.1501L2 30.6127L13.9995 23.075L26.001 30.6127L13.9995 38.1501Z"
      fill="#0061FE"
    />
    <Path
      d="M26.001 30.6127L38.0005 23.075L50 30.6127L38.0005 38.1501L26.001 30.6127Z"
      fill="#0061FE"
    />
    <Path
      d="M26.001 48.2L13.9995 40.6625L26.001 33.125L38.0005 40.6625L26.001 48.2Z"
      fill="#0061FE"
    />
  </Svg>
);
export default SvgDropbox;
