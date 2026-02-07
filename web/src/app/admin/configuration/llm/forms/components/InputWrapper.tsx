import * as GeneralLayouts from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";

interface DescriptionLink {
  text: string;
  href: string;
}

interface InputWrapperProps {
  label: string;
  description?: string;
  descriptionLink?: DescriptionLink;
  children: React.ReactNode;
  optional?: boolean;
}

export default function InputWrapper({
  label,
  optional,
  description,
  descriptionLink,
  children,
}: InputWrapperProps) {
  const renderDescription = () => {
    if (!description) return null;

    if (descriptionLink && description.includes("{link}")) {
      const [before, after] = description.split("{link}");
      return (
        <Text as="p" secondaryBody text03>
          {before}
          <a
            href={descriptionLink.href}
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
          >
            {descriptionLink.text}
          </a>
          {after}
        </Text>
      );
    }

    return (
      <Text as="p" secondaryBody text03>
        {description}
      </Text>
    );
  };

  return (
    <GeneralLayouts.Section
      flexDirection="column"
      alignItems="start"
      gap={0.25}
    >
      <GeneralLayouts.Section
        flexDirection="row"
        gap={0.25}
        alignItems="center"
        justifyContent="start"
      >
        <Text as="p">{label}</Text>
        {optional && (
          <Text as="p" text03>
            (Optional)
          </Text>
        )}
      </GeneralLayouts.Section>
      {children}
      {renderDescription()}
    </GeneralLayouts.Section>
  );
}
