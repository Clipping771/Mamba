"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button, ErrorBanner, Field, Input, Notice } from "@/components/ui";
import { api, call } from "@/lib/api";

export function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setError(new Error("Passwords do not match."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await call(api.POST("/auth/password-reset/confirm", { body: { token, password } }));
      setDone(result.message);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (!token) return <ErrorBanner error={new Error("This reset link is incomplete.")} />;
  if (done) {
    return (
      <div className="space-y-4">
        <Notice>{done}</Notice>
        <Link href="/login" className="text-sm text-emerald-400">
          Sign in →
        </Link>
      </div>
    );
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <h1 className="text-lg font-semibold text-white">Choose a new password</h1>
      <ErrorBanner error={error} />
      <Field label="New password" hint="At least 12 characters. All your sessions will be signed out.">
        <Input type="password" required minLength={12} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      <Field label="Confirm password">
        <Input type="password" required minLength={12} autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </Field>
      <Button type="submit" className="w-full" busy={busy}>
        Update password
      </Button>
    </form>
  );
}
