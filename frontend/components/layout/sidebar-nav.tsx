"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { navigationGroups } from "@/lib/navigation";
import { cn } from "@/lib/utils";

export function SidebarNav({ compact = false }: { compact?: boolean }) {
  const pathname = usePathname();

  return (
    <nav
      aria-label="主导航"
      className={compact ? "flex min-w-max gap-2 px-4 py-3" : "space-y-6 px-3 py-4"}
    >
      {navigationGroups.map((group) => (
        <div className={cn(compact && "contents")} key={group.label}>
          {!compact && (
            <p className="mb-2 px-3 text-xs font-semibold tracking-[0.12em] text-muted-foreground uppercase">
              {group.label}
            </p>
          )}
          <div className={cn(compact ? "contents" : "space-y-1")}>
            {group.items.map((item) => {
              const active =
                pathname === item.href ||
                (item.href !== "/dashboard" && pathname.startsWith(`${item.href}/`));
              const Icon = item.icon;

              return (
                <Link
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    active
                      ? "bg-sidebar-primary text-sidebar-primary-foreground shadow-sm"
                      : "text-sidebar-foreground/75 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                    compact && "whitespace-nowrap",
                  )}
                  href={item.href}
                  key={item.href}
                >
                  <Icon aria-hidden="true" className="size-4" />
                  {item.label}
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}

