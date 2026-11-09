"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Button, ErrorBanner, Field, Input, Notice } from "@/components/ui";
import { api, call } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await call(api.POST("/auth/password-reset/request", { body: { email } }));
      setMessage(result.message);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-white">Reset your password</h1>
        <p className="text-sm text-zinc-400">
          If email is not set up for your organisation, ask your administrator for a reset link.
        </p>
      </div>
      <ErrorBanner error={error} />
      {message ? (
        <Notice>{message}</Notice>
      ) : (
        <>
          <Field label="Email">
            <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Button type="submit" className="w-full" busy={busy}>
            Send reset link
          </Button>
        </>
      )}
      <Link href="/login" className="block text-sm text-zinc-400 hover:text-zinc-200">
        ← Back to sign in
      </Link>
    </form>
  );
}
