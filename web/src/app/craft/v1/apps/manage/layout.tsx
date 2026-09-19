import { createCraftManageLayout } from "@/layouts/craft/CraftManageLayout";
import { Permission } from "@/lib/types";

export default createCraftManageLayout(Permission.FULL_ADMIN_PANEL_ACCESS);
