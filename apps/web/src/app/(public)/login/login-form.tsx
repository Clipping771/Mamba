"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { homeFor } from "@/components/app-shell";
import { Button, ErrorBanner, Field, Input } from "@/components/ui";
import { api, call, CSRF_HEADERS, toApiError } from "@/lib/api";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needsCode, setNeedsCode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...CSRF_HEADERS },
        body: JSON.stringify({ email, password, totp_code: needsCode ? code : null }),
      });
      if (!response.ok) {
        const err = toApiError(response.status, await response.json().catch(() => ({})));
        if (err.code === "totp_required") {
          setNeedsCode(true);
          return;
        }
        throw err;
      }
      const me = await call(api.GET("/auth/me"));
      const next = params.get("next");
      const safeNext = next && next.startsWith("/") && !next.startsWith("//") ? next : null;
      router.replace(me.requires_2fa_setup ? "/settings/security" : (safeNext ?? homeFor(me.role)));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-white">{needsCode ? "Two-factor authentication" : "Sign in"}</h1>
        <p className="text-sm text-zinc-400">
          {needsCode ? "Enter the 6-digit code from your authenticator app." : "Invite-only access for vetted teams."}
        </p>
      </div>
      <ErrorBanner error={error} />
      {!needsCode ? (
        <>
          <Field label="Email">
            <Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Password">
            <Input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
        </>
      ) : (
        <Field label="Authentication code">
          <Input
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9 ]{6,7}"
            maxLength={7}
            required
            autoFocus
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="text-center font-mono text-lg tracking-[0.4em]"
          />
        </Field>
      )}
      <Button type="submit" className="w-full" busy={busy}>
        {needsCode ? "Verify" : "Sign in"}
      </Button>
      <div className="flex justify-between text-sm">
        {needsCode ? (
          <button type="button" className="text-zinc-400 hover:text-zinc-200" onClick={() => setNeedsCode(false)}>
            ← Back
          </button>
        ) : (
          <Link href="/forgot-password" className="text-zinc-400 hover:text-zinc-200">
            Forgot password?
          </Link>
        )}
        <Link href="/apply" className="text-emerald-400 hover:text-emerald-300">
          Apply for access
        </Link>
      </div>
    </form>
  );
}
