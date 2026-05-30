import { View } from "react-native";

import { Button, Card, Tag, Text } from "@/components/opal";

// Showcase / smoke-test for the opal-native display components (doc 05).
export default function Settings() {
  return (
    <View className="flex-1 bg-background-neutral-00 p-4">
      <Card className="gap-3">
        <View className="flex-row items-center justify-between">
          <Text font="heading-h3" color="text-05">
            Display components
          </Text>
          <Tag tone="success">New</Tag>
        </View>

        <Text font="main-ui-body" color="text-03">
          These opal-native components mirror the web Opal API on React Native,
          consuming the doc-03 token system for typography and color.
        </Text>

        <View className="flex-row gap-2 pt-1">
          <Button variant="default" prominence="primary" onPress={() => {}}>
            Save
          </Button>
          <Button variant="danger" prominence="primary" onPress={() => {}}>
            Delete
          </Button>
        </View>
      </Card>
    </View>
  );
}
