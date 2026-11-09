"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button, ErrorBanner, Field, Input, Loading, Notice } from "@/components/ui";
import { api, call, ROLE_LABELS } from "@/lib/api";
import { useQuery } from "@/lib/hooks";

export function AcceptInvite() {
  const token = useSearchParams().get("token") ?? "";
  const invite = useQuery(token ? ["invite", token] : null, () =>
    call(api.POST("/auth/invite/inspect", { body: { token } })),
  );
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setError(new Error("Passwords do not match."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await call(api.POST("/auth/invite/accept", { body: { token, name, password } }));
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (!token) return <ErrorBanner error={new Error("This invitation link is incomplete.")} />;
  if (invite.isLoading) return <Loading />;
  if (invite.error) return <ErrorBanner error={invite.error} />;
  if (done) {
    return (
      <div className="space-y-4">
        <Notice>Your account is ready.</Notice>
        <Link href="/login" className="text-sm text-emerald-400">
          Sign in →
        </Link>
      </div>
    );
  }
  const data = invite.data!;

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-white">Join {data.org_name ?? "BLACK MAMBA"}</h1>
        <p className="text-sm text-zinc-400">
          You were invited as <strong className="text-zinc-200">{ROLE_LABELS[data.role]}</strong> ({data.email}).
        </p>
      </div>
      <ErrorBanner error={error} />
      <Field label="Your name">
        <Input required autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Password" hint="At least 12 characters. A passphrase works well.">
        <Input
          type="password"
          required
          minLength={12}
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </Field>
      <Field label="Confirm password">
        <Input type="password" required minLength={12} autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </Field>
      <Button type="submit" className="w-full" busy={busy}>
        Create account
      </Button>
    </form>
  );
}
