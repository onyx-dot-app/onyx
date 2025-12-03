// Template for SVGR to generate icon components with size prop support
const template = (variables, { tpl }) => {
  return tpl`
${variables.imports};

${variables.interfaces};

const ${
    variables.componentName
  } = ({ size, ...props }: SVGProps<SVGSVGElement> & { size?: number }) => (
  ${
    variables.jsx.type === "JSXElement" &&
    variables.jsx.openingElement.name.name === "svg"
      ? tpl`<svg width={size} height={size} ${variables.jsx.openingElement.attributes.filter(
          (attr) =>
            attr.type === "JSXAttribute" &&
            attr.name.name !== "width" &&
            attr.name.name !== "height"
        )} {...props}>${variables.jsx.children}</svg>`
      : variables.jsx
  }
);

${variables.exports};
`;
};

module.exports = template;
