import { Text } from "@opal/components";
export interface CharacterCountProps {
  value: string;
  limit: number;
}
export default function CharacterCount({ value, limit }: CharacterCountProps) {
  const length = value?.length || 0;
  return (
    <Text color="text-03" font="secondary-body">
      {`(${length}/${limit} characters)`}
    </Text>
  );
}
