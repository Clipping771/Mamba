"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button, Card, ErrorBanner, Field, Input, LinkButton, PageHeader, Select, Textarea } from "@/components/ui";
import { api, call, CATEGORY_LABELS, type CaseCategory } from "@/lib/api";
import { useInvalidate, useMe, useQuery } from "@/lib/hooks";

export default function NewCasePage() {
  const router = useRouter();
  const invalidate = useInvalidate();
  const { data: me } = useMe();
  const members = useQuery(["members"], () => call(api.GET("/members")));
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<CaseCategory>("job_scam");
  const [description, setDescription] = useState("");
  const [leadId, setLeadId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await call(
        api.POST("/cases", { body: { title, category, description, lead_id: leadId || null } }),
      );
      await invalidate("cases");
      router.push(`/cases/${created.id}`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="New case" subtitle="Describe the scam infrastructure, not private individuals." />
      <Card className="max-w-2xl">
        <form onSubmit={submit} className="space-y-4">
          <ErrorBanner error={error} />
          <Field label="Title" hint="e.g. 'Fake courier job ads on social media'">
            <Input required minLength={3} maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label="Category">
            <Select value={category} onChange={(e) => setCategory(e.target.value as CaseCategory)}>
              {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Description" hint="What was reported, where it appeared, and what you want to establish.">
            <Textarea rows={6} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <Field label="Case lead">
            <Select value={leadId} onChange={(e) => setLeadId(e.target.value)}>
              <option value="">Me ({me?.name})</option>
              {members.data
                ?.filter((m) => m.id !== me?.id)
                .map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name} ({m.role})
                  </option>
                ))}
            </Select>
          </Field>
          <div className="flex gap-2">
            <Button type="submit" busy={busy}>
              Create case
            </Button>
            <LinkButton href="/cases">Cancel</LinkButton>
          </div>
        </form>
      </Card>
    </>
  );
}
