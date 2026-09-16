import type { ReactNode } from "react";

import { AppShell } from "@/components/layout/app-shell";

export default function PlatformLayout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}

