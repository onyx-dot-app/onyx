const template = (variables, { tpl }) => {
  return tpl`
import type { IconProps } from "@opal/types";

const ${variables.componentName} = ({ size, ...props }: IconProps) => (
  ${variables.jsx}
);

${variables.exports};
`;
};

export default template;
