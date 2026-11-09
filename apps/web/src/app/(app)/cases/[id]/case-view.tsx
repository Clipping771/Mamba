"use client";

import { useState, type FormEvent } from "react";

import {
  Button,
  Card,
  ErrorBanner,
  Field,
  Input,
  LinkButton,
  Loading,
  PageHeader,
  Select,
  StatusBadge,
  Tabs,
  Textarea,
} from "@/components/ui";
import { api, call, CATEGORY_LABELS, STATUS_LABELS, type CaseCategory, type CaseStatus } from "@/lib/api";
import { useInvalidate, useMe, useQuery } from "@/lib/hooks";

import { ActivityTab } from "./activity-tab";
import { ArchiveTab } from "./archive-tab";
import { EvidenceTab } from "./evidence-tab";
import { FindingsTab } from "./findings-tab";
import { NotesTab } from "./notes-tab";

type TabId = "evidence" | "findings" | "notes" | "archive" | "activity";

const TRANSITION_LABELS: Record<CaseStatus, string> = {
  open: "Reopen case",
  investigating: "Start investigating",
  review: "Send to review",
  closed: "Close case",
};

export function CaseView({ id }: { id: string }) {
  const { data: me } = useMe();
  const invalidate = useInvalidate();
  const caseQuery = useQuery(["case", id], () => call(api.GET("/cases/{case_id}", { params: { path: { case_id: id } } })));
  const members = useQuery(["members"], () => call(api.GET("/members")));
  const [tab, setTab] = useState<TabId>("evidence");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (caseQuery.isLoading) return <Loading />;
  if (caseQuery.error || !caseQuery.data) return <ErrorBanner error={caseQuery.error ?? new Error("Case not found")} />;
  const c = caseQuery.data;
  const names = new Map((members.data ?? []).map((m) => [m.id, m.name]));
  // Revalidates every query about this case (summary, tabs, report preview) and the list.
  const refresh = async () => {
    await invalidate(id, "cases");
  };

  async function transition(status: CaseStatus) {
    if (status === "closed" && !window.confirm("Close this case? It becomes read-only until a reviewer reopens it.")) return;
    setBusy(true);
    setError(null);
    try {
      await call(api.POST("/cases/{case_id}/transition", { params: { path: { case_id: id } }, body: { status } }));
      await refresh();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title={c.title}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge status={c.status} label={STATUS_LABELS[c.status]} />
            <span>{CATEGORY_LABELS[c.category]}</span>
            <span>· Lead: {c.lead_name}</span>
          </span>
        }
        actions={
          <>
            {c.can_edit && (
              <LinkButton href={`/cases/${id}/evidence/new`} variant="primary">
                Add evidence
              </LinkButton>
            )}
            <LinkButton href={`/cases/${id}/report`}>Report</LinkButton>
            {c.can_edit && (
              <Button variant="secondary" onClick={() => setEditing((e) => !e)}>
                {editing ? "Cancel edit" : "Edit"}
              </Button>
            )}
          </>
        }
      />
      <ErrorBanner error={error} />
      {editing ? (
        <EditCase
          id={id}
          initial={{ title: c.title, category: c.category, description: c.description, lead_id: c.lead_id }}
          members={members.data ?? []}
          onSaved={async () => {
            setEditing(false);
            await refresh();
          }}
        />
      ) : (
        <Card className="mb-6">
          <p className="text-sm whitespace-pre-wrap text-zinc-300">{c.description || "No description yet."}</p>
          {c.allowed_transitions && c.allowed_transitions.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2 border-t border-zinc-800 pt-4">
              {c.allowed_transitions.map((status) => (
                <Button
                  key={status}
                  variant={status === "closed" ? "danger" : "secondary"}
                  busy={busy}
                  onClick={() => transition(status)}
                >
                  {TRANSITION_LABELS[status]}
                </Button>
              ))}
            </div>
          )}
        </Card>
      )}
      <Tabs<TabId>
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "evidence", label: `Evidence (${c.evidence_count})` },
          { id: "findings", label: "Findings" },
          { id: "notes", label: "Notes & ARCHIVIST" },
          { id: "archive", label: "Archive a URL" },
          { id: "activity", label: "Chain of custody" },
        ]}
      />
      {tab === "evidence" && <EvidenceTab caseId={id} canEdit={!!c.can_edit} names={names} onChange={refresh} />}
      {tab === "findings" && me && (
        <FindingsTab caseId={id} canEdit={!!c.can_edit} me={me} names={names} onChange={refresh} />
      )}
      {tab === "notes" && <NotesTab caseId={id} canEdit={!!c.can_edit} names={names} />}
      {tab === "archive" && <ArchiveTab caseId={id} canEdit={!!c.can_edit} onDone={refresh} />}
      {tab === "activity" && <ActivityTab caseId={id} />}
    </>
  );
}

function EditCase({
  id,
  initial,
  members,
  onSaved,
}: {
  id: string;
  initial: { title: string; category: CaseCategory; description: string; lead_id: string };
  members: { id: string; name: string; role: string }[];
  onSaved: () => Promise<void>;
}) {
  const [form, setForm] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await call(api.PATCH("/cases/{case_id}", { params: { path: { case_id: id } }, body: form }));
      await onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-6">
      <form onSubmit={submit} className="space-y-4">
        <ErrorBanner error={error} />
        <Field label="Title">
          <Input required minLength={3} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Category">
            <Select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as CaseCategory })}>
              {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Lead">
            <Select value={form.lead_id} onChange={(e) => setForm({ ...form, lead_id: e.target.value })}>
              {members.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} ({m.role})
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Description">
          <Textarea rows={5} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>
        <Button type="submit" busy={busy}>
          Save changes
        </Button>
      </form>
    </Card>
  );
}
