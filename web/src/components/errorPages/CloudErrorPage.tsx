import Text from "@/refresh-components/texts/Text";
import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";
import { DEFAULT_APPLICATION_NAME } from "@/lib/constants";

export default function CloudError() {
  return (
    <ErrorPageLayout>
      <Text as="p" headingH2>
        Maintenance in Progress
      </Text>

      <Text as="p" text03>
        {DEFAULT_APPLICATION_NAME} está en una ventana de mantenimiento.
        Inténtalo de nuevo en un par de minutos.
      </Text>

      <Text as="p" text03>
        We apologize for any inconvenience this may cause and appreciate your
        patience.
      </Text>
    </ErrorPageLayout>
  );
}
