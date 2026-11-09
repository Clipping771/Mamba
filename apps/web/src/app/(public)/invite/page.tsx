import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { AcceptInvite } from "./accept-invite";

export const metadata: Metadata = { title: "Accept invitation" };

export default function InvitePage() {
  return (
    <Suspense fallback={<Loading />}>
      <AcceptInvite />
    </Suspense>
  );
}
