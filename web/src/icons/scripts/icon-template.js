// Template for SVGR to generate icon components with size prop support
const template = (variables, { tpl }) => {
  return tpl`
import { IconProps } from "@/icons";

const ${variables.componentName} = ({ size, ...props }: IconProps) => (
  ${variables.jsx}
);

${variables.exports};
`;
};

module.exports = template;
