import Text from "@/refresh-components/texts/Text";
import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";

export default function CloudError() {
  return (
    <ErrorPageLayout>
      <Text headingH2>Maintenance in Progress</Text>

      <Text text03>
        Onyx is currently in a maintenance window. Please check back in a couple
        of minutes.
      </Text>

      <Text text03>
        We apologize for any inconvenience this may cause and appreciate your
        patience.
      </Text>
    </ErrorPageLayout>
  );
}
