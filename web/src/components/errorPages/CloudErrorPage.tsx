import { AuthLayouts } from "@opal/layouts";

export default function CloudError() {
  return (
    <AuthLayouts.Root>
      <AuthLayouts.Card
        title="Maintenance in Progress"
        description="Onyx is currently in a maintenance window."
      >
        <AuthLayouts.Message
          title="We'll be back soon."
          description="Please check back in a couple of minutes. We apologize for any inconvenience."
        />
      </AuthLayouts.Card>
    </AuthLayouts.Root>
  );
}
