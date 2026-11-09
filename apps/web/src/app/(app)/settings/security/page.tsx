"use client";

import { useRouter } from "next/navigation";
import QRCode from "qrcode";
import { useState, type FormEvent } from "react";

import { Badge, Button, Card, ErrorBanner, Field, Input, Mono, Notice, PageHeader } from "@/components/ui";
import { api, call } from "@/lib/api";
import { useMe } from "@/lib/hooks";

export default function SecurityPage() {
  const me = useMe();
  return (
    <>
      <PageHeader title="Security" subtitle={me.data?.email} />
      <div className="grid gap-6 lg:grid-cols-2">
        <TwoFactor />
        <ChangePassword />
      </div>
    </>
  );
}

function TwoFactor() {
  const me = useMe();
  const [setup, setSetup] = useState<{ secret: string; qr: string } | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const enabled = me.data?.totp_enabled;
  const isAdmin = me.data?.role === "admin" || me.data?.role === "platform_admin";

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const result = await call(api.POST("/auth/2fa/setup"));
      const qr = await QRCode.toDataURL(result.otpauth_uri, { margin: 1, width: 220 });
      setSetup({ secret: result.secret, qr });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await call(api.POST("/auth/2fa/enable", { body: { code } }));
      setSetup(null);
      setDone(true);
      await me.mutate();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    const c = window.prompt("Enter a current code from your authenticator app to turn 2FA off");
    if (!c) return;
    setBusy(true);
    setError(null);
    try {
      await call(api.POST("/auth/2fa/disable", { body: { code: c } }));
      await me.mutate();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="flex items-center justify-between">
        <h2 className="font-medium text-white">Two-factor authentication</h2>
        {enabled ? <Badge tone="green">On</Badge> : <Badge tone="amber">Off</Badge>}
      </div>
      <p className="mt-1 text-sm text-zinc-400">
        Use an authenticator app (Aegis, Google Authenticator, 1Password…). Required for administrators.
      </p>
      <div className="mt-4 space-y-3">
        <ErrorBanner error={error} />
        {done && <Notice>2FA is on. You will be asked for a code each time you sign in.</Notice>}
        {!enabled && !setup && (
          <Button busy={busy} onClick={start}>
            Set up 2FA
          </Button>
        )}
        {setup && (
          <form onSubmit={confirm} className="space-y-3">
            {/* eslint-disable-next-line @next/next/no-img-element -- local data URL */}
            <img src={setup.qr} alt="QR code for your authenticator app" className="rounded bg-white p-2" width={220} height={220} />
            <p className="text-xs text-zinc-400">
              Can&apos;t scan? Enter this key: <Mono className="text-zinc-200">{setup.secret}</Mono>
            </p>
            <Field label="6-digit code">
              <Input
                inputMode="numeric"
                autoComplete="one-time-code"
                required
                maxLength={7}
                value={code}
                onChange={(e) => setCode(e.target.value)}
                className="max-w-40 text-center font-mono tracking-[0.3em]"
              />
            </Field>
            <Button type="submit" busy={busy}>
              Turn on 2FA
            </Button>
          </form>
        )}
        {enabled && !isAdmin && (
          <Button variant="ghost" busy={busy} onClick={disable}>
            Turn off 2FA
          </Button>
        )}
      </div>
    </Card>
  );
}

function ChangePassword() {
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      // The API revokes every other session; sign in again here with the new password.
      await call(api.POST("/auth/change-password", { body: { current_password: current, new_password: next } }));
      setDone(true);
      setCurrent("");
      setNext("");
      setTimeout(() => router.replace("/login"), 1500);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <h2 className="font-medium text-white">Change password</h2>
      <form onSubmit={submit} className="mt-4 space-y-3">
        <ErrorBanner error={error} />
        {done && <Notice>Password changed. Signing you out of all sessions…</Notice>}
        <Field label="Current password">
          <Input type="password" required autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </Field>
        <Field label="New password" hint="At least 12 characters.">
          <Input type="password" required minLength={12} autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        </Field>
        <Button type="submit" busy={busy}>
          Change password
        </Button>
      </form>
    </Card>
  );
}
