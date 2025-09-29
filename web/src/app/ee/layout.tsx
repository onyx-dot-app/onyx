import i18n from "@/i18n/init-server";
import k from "@/i18n/keys";
import { SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED } from "@/lib/constants";

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  if (!SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    return (
      <div className="flex h-screen">
        <div className="mx-auto my-auto text-lg font-bold text-red-500">
          {i18n.t(k.THIS_FUNCITONALITY_IS_ONLY_AVA)}
        </div>
      </div>
    );
  }

  return children;
}
