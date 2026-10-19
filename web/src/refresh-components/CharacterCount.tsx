import { Text } from "@opal/components";
export interface CharacterCountProps {
  value: string;
  limit: number;
}
export default function CharacterCount({ value, limit }: CharacterCountProps) {
  const length = value?.length || 0;
  return (
    <Text font="secondary-body" color="text-03">
      {`(${length}/${limit} characters)`}
    </Text>
  );
}
