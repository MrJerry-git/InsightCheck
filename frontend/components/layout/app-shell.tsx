import type { ReactNode } from "react";
import { Activity, ShieldPlus } from "lucide-react";

import { SidebarNav } from "@/components/layout/sidebar-nav";
import { MedicalDisclaimer } from "@/components/shared/medical-disclaimer";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[17rem_1fr]">
      <aside className="hidden border-r border-sidebar-border bg-sidebar lg:block">
        <div className="sticky top-0 flex h-screen flex-col">
          <div className="flex h-20 items-center gap-3 px-6">
            <span className="grid size-10 place-items-center rounded-xl bg-sidebar-primary text-sidebar-primary-foreground shadow-sm">
              <ShieldPlus aria-hidden="true" className="size-5" />
            </span>
            <div>
              <p className="text-base font-bold tracking-tight">循影定检</p>
              <p className="text-xs text-muted-foreground">纵向健康辅助分析</p>
            </div>
          </div>
          <Separator />
          <div className="min-h-0 flex-1 overflow-y-auto">
            <SidebarNav />
          </div>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-20 border-b bg-background/92 backdrop-blur">
          <div className="flex h-16 items-center justify-between px-4 sm:px-6 lg:px-8">
            <div className="flex items-center gap-2 lg:hidden">
              <ShieldPlus aria-hidden="true" className="size-5 text-primary" />
              <span className="font-bold">循影定检</span>
            </div>
            <div className="hidden items-center gap-2 text-sm text-muted-foreground lg:flex">
              <Activity aria-hidden="true" className="size-4 text-primary" />
              工程骨架运行中
            </div>
            <Badge variant="outline">第一阶段</Badge>
          </div>
          <div className="overflow-x-auto border-t lg:hidden">
            <SidebarNav compact />
          </div>
        </header>

        <main className="mx-auto w-full max-w-[96rem] p-4 sm:p-6 lg:p-8">{children}</main>
        <footer className="mx-auto w-full max-w-[96rem] px-4 pb-8 sm:px-6 lg:px-8">
          <MedicalDisclaimer />
        </footer>
      </div>
    </div>
  );
}

