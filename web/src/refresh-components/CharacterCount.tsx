import Text from "@/refresh-components/texts/Text";
export interface CharacterCountProps {
  value: string;
  limit: number;
}
export default function CharacterCount({ value, limit }: CharacterCountProps) {
  const length = value?.length || 0;
  return (
    <Text text03 secondaryBody>
      ({length}/{limit} characters)
    </Text>
  );
}
