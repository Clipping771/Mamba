"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Button, ErrorBanner, Field, Input, Notice, Textarea } from "@/components/ui";
import { api, call } from "@/lib/api";

export default function ApplyPage() {
  const [form, setForm] = useState({ org_name: "", contact_name: "", contact_email: "", purpose: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await call(api.POST("/orgs/apply", { body: form }));
      setDone(result.message);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="space-y-4">
        <Notice>{done}</Notice>
        <Link href="/login" className="text-sm text-emerald-400">
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-white">Apply for access</h1>
        <p className="text-sm text-zinc-400">
          BLACK MAMBA is free for vetted non-profits, victim-support groups and investigation teams. Every
          application is reviewed by a person.
        </p>
      </div>
      <ErrorBanner error={error} />
      <Field label="Organisation name">
        <Input required minLength={2} value={form.org_name} onChange={(e) => setForm({ ...form, org_name: e.target.value })} />
      </Field>
      <Field label="Your name">
        <Input required value={form.contact_name} onChange={(e) => setForm({ ...form, contact_name: e.target.value })} />
      </Field>
      <Field label="Work email" hint="We will send the administrator invitation here.">
        <Input
          type="email"
          required
          value={form.contact_email}
          onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
        />
      </Field>
      <Field label="What will you use BLACK MAMBA for?" hint="At least 20 characters. Who you help, and how.">
        <Textarea required minLength={20} value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })} />
      </Field>
      <Button type="submit" className="w-full" busy={busy}>
        Submit application
      </Button>
      <p className="text-xs text-zinc-500">
        By applying you agree to work under the BLACK MAMBA Code: no doxxing, no harassment, allegations are not
        proof, and only lawful collection of public or consented information.
      </p>
    </form>
  );
}
