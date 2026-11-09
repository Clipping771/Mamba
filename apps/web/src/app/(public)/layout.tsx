import Link from "next/link";

import { Logo } from "@/components/logo";

export default function PublicLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4 py-12">
      <Link href="/login" className="mb-8">
        <Logo size="lg" />
      </Link>
      <div className="w-full max-w-md rounded-xl border border-zinc-800 bg-zinc-900/70 p-6 shadow-2xl shadow-black/40">
        {children}
      </div>
      <p className="mt-8 max-w-md text-center text-xs text-zinc-500">
        Protect the innocent. Expose the guilty. Never become what we fight.
      </p>
    </div>
  );
}
