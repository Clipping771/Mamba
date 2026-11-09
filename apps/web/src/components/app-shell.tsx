"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { Logo } from "@/components/logo";
import { Button, cx, Loading, Notice } from "@/components/ui";
import { CSRF_HEADERS, ROLE_LABELS, type Role } from "@/lib/api";
import { useMe } from "@/lib/hooks";

type NavItem = { href: string; label: string; roles: Role[] };

const NAV: NavItem[] = [
  { href: "/cases", label: "Cases", roles: ["investigator", "reviewer"] },
  { href: "/review", label: "Review queue", roles: ["reviewer"] },
  { href: "/admin/users", label: "Users & invites", roles: ["admin"] },
  { href: "/admin/audit", label: "Audit log", roles: ["admin"] },
  { href: "/platform/orgs", label: "Organisations", roles: ["platform_admin"] },
  { href: "/settings/security", label: "Security", roles: ["investigator", "reviewer", "admin", "platform_admin"] },
];

export function homeFor(role: Role | undefined): string {
  if (role === "admin") return "/admin/users";
  if (role === "platform_admin") return "/platform/orgs";
  return "/cases";
}

export function AppShell({ children }: { children: ReactNode }) {
  const { data: me, isLoading } = useMe();
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST", headers: CSRF_HEADERS });
    router.replace("/login");
  }

  if (isLoading || !me) return <Loading label="Signing you in…" />;
  const items = NAV.filter((item) => item.roles.includes(me.role));
  const mustSetup2fa = me.requires_2fa_setup && pathname !== "/settings/security";

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="border-b border-zinc-800 bg-zinc-950 md:sticky md:top-0 md:h-screen md:w-60 md:shrink-0 md:border-r md:border-b-0">
        <div className="flex items-center justify-between px-4 py-4">
          <Link href={homeFor(me.role)} className="flex items-center gap-2">
            <Logo />
          </Link>
          <button
            className="rounded-md p-2 text-zinc-400 hover:bg-zinc-800 md:hidden"
            onClick={() => setOpen((o) => !o)}
            aria-label="Toggle navigation"
            aria-expanded={open}
          >
            ☰
          </button>
        </div>
        <nav className={cx("space-y-0.5 px-2 pb-4 md:block", open ? "block" : "hidden")}>
          {items.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setOpen(false)}
                className={cx(
                  "block rounded-md px-3 py-2 text-sm transition-colors",
                  active ? "bg-zinc-800 font-medium text-white" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100",
                )}
              >
                {item.label}
              </Link>
            );
          })}
          <div className="mt-6 border-t border-zinc-800 px-3 pt-4 text-xs text-zinc-500">
            <div className="truncate text-sm text-zinc-300">{me.name}</div>
            <div className="truncate">{me.org_name ?? "Platform"}</div>
            <div>{ROLE_LABELS[me.role]}</div>
            <Button variant="ghost" className="mt-3 -ml-3" onClick={logout}>
              Sign out
            </Button>
          </div>
        </nav>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-6 md:px-8 md:py-8">
        <div className="mx-auto max-w-6xl">
          {mustSetup2fa ? (
            <div className="space-y-4">
              <Notice tone="amber">
                Administrators must turn on two-factor authentication before they can manage anything.
              </Notice>
              <Link href="/settings/security" className="text-sm text-emerald-400 underline">
                Set up 2FA now
              </Link>
            </div>
          ) : (
            children
          )}
        </div>
      </main>
    </div>
  );
}
