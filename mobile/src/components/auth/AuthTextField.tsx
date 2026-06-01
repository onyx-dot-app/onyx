import { TextInput, View, type TextInputProps } from "react-native";

import { Text } from "@/components/opal";
import { useThemeColors } from "@/theme/ThemeProvider";

interface AuthTextFieldProps extends TextInputProps {
  label: string;
}

export function AuthTextField({ label, ...inputProps }: AuthTextFieldProps) {
  const colors = useThemeColors();

  return (
    <View className="gap-1">
      <Text font="secondary-body" color="text-04">
        {label}
      </Text>
      <TextInput
        className="rounded-[8px] border border-border-02 px-3 py-2 text-text-05"
        placeholderTextColor={colors["text-03"]}
        autoCapitalize="none"
        autoCorrect={false}
        {...inputProps}
      />
    </View>
  );
}
