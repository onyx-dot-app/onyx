// Template for SVGR to generate icon components with size prop support
const template = (variables, { tpl }) => {
  // Add stroke="currentColor" to the svg element for default coloring
  const jsxWithStroke = {
    ...variables.jsx,
    openingElement: {
      ...variables.jsx.openingElement,
      attributes: [
        ...variables.jsx.openingElement.attributes,
        tpl`stroke="currentColor"`,
      ],
    },
  };

  return tpl`
import { IconProps } from "@/icons";

const ${variables.componentName} = ({ size, ...props }: IconProps) => (
  ${jsxWithStroke}
);

${variables.exports};
`;
};

module.exports = template;
