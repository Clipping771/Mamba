import { Suspense } from "react";

import { AppShell } from "@/components/app-shell";
import { Loading } from "@/components/ui";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <Suspense fallback={<Loading />}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
