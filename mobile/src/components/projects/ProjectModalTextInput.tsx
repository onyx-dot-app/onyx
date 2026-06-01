import { TextInput, type TextInputProps } from "react-native";

import { typography } from "@/theme/generated/typography";
import { useToken } from "@/theme/ThemeProvider";

// Shared themed text field for the project modals; owns border/typography/color tokens.
export function ProjectModalTextInput({ style, ...rest }: TextInputProps) {
  const placeholderColor = useToken("text-03");
  const typedColor = useToken("text-05");

  return (
    <TextInput
      placeholderTextColor={placeholderColor}
      className="rounded-[8px] border border-border-02 bg-background-neutral-00 px-3 py-2"
      style={[typography["main-ui-body"], { color: typedColor }, style]}
      {...rest}
    />
  );
}
