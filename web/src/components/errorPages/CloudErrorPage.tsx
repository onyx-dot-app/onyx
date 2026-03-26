import { Text } from "@opal/components";
import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";

export default function CloudError() {
  return (
    <ErrorPageLayout>
      <Text as="p" font="heading-h2" color="text-05">
        Maintenance in Progress
      </Text>

      <Text as="p" color="text-03">
        Onyx is currently in a maintenance window. Please check back in a couple
        of minutes.
      </Text>

      <Text as="p" color="text-03">
        We apologize for any inconvenience this may cause and appreciate your
        patience.
      </Text>
    </ErrorPageLayout>
  );
}
