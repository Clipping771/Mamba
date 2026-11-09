import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { ResetForm } from "./reset-form";

export const metadata: Metadata = { title: "Choose a new password" };

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ResetForm />
    </Suspense>
  );
}
