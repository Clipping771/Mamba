"use client";

import { useState, type FormEvent } from "react";

import { Button, Card, EmptyState, ErrorBanner, Field, Loading, StatusBadge, Textarea } from "@/components/ui";
import { api, call, evidenceRefs, formatDate, type Evidence, type Finding, type Me } from "@/lib/api";
import { useQuery } from "@/lib/hooks";

export function FindingsTab({
  caseId,
  canEdit,
  me,
  names,
  onChange,
}: {
  caseId: string;
  canEdit: boolean;
  me: Me;
  names: Map<string, string>;
  onChange: () => void;
}) {
  const findings = useQuery(["findings", caseId], () =>
    call(api.GET("/cases/{case_id}/findings", { params: { path: { case_id: caseId } } })),
  );
  const evidence = useQuery(["evidence", caseId], () =>
    call(api.GET("/cases/{case_id}/evidence", { params: { path: { case_id: caseId } } })),
  );
  const refresh = () => {
    findings.mutate();
    onChange();
  };

  if (findings.isLoading || evidence.isLoading) return <Loading />;
  const allEvidence = evidence.data ?? [];
  const refs = evidenceRefs(allEvidence);
  const usable = allEvidence.filter((e) => !e.excluded && e.type !== "report");

  return (
    <div className="space-y-6">
      <ErrorBanner error={findings.error ?? evidence.error} />
      <p className="text-sm text-zinc-400">
        A finding is a claim backed by evidence. It reaches a report only after a reviewer who is not its author
        verifies it.
      </p>
      {canEdit && <NewFinding caseId={caseId} evidence={usable} refs={refs} onCreated={refresh} />}
      {(findings.data ?? []).length === 0 ? (
        <EmptyState title="No findings yet" />
      ) : (
        <div className="space-y-3">
          {findings.data!.map((f) => (
            <FindingCard
              key={f.id}
              finding={f}
              me={me}
              canEdit={canEdit}
              names={names}
              refs={refs}
              evidence={usable}
              onChange={refresh}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function EvidencePicker({
  evidence,
  refs,
  selected,
  onChange,
}: {
  evidence: Evidence[];
  refs: Map<string, string>;
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  if (evidence.length === 0) return <p className="text-sm text-amber-300">Add evidence to the case first.</p>;
  return (
    <div className="max-h-56 space-y-1 overflow-y-auto rounded-md border border-zinc-800 p-2">
      {evidence.map((e) => (
        <label key={e.id} className="flex items-start gap-2 rounded px-2 py-1 text-sm hover:bg-zinc-800/60">
          <input
            type="checkbox"
            className="mt-1 accent-emerald-500"
            checked={selected.includes(e.id)}
            onChange={(ev) => onChange(ev.target.checked ? [...selected, e.id] : selected.filter((id) => id !== e.id))}
          />
          <span>
            <span className="font-mono text-xs text-zinc-500">{refs.get(e.id)}</span>{" "}
            <span className="text-zinc-200">{e.title || e.type}</span>{" "}
            <span className="text-xs text-zinc-500">({e.type})</span>
          </span>
        </label>
      ))}
    </div>
  );
}

function NewFinding({
  caseId,
  evidence,
  refs,
  onCreated,
}: {
  caseId: string;
  evidence: Evidence[];
  refs: Map<string, string>;
  onCreated: () => void;
}) {
  const [claim, setClaim] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (selected.length === 0) {
      setError(new Error("Cite at least one evidence item."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await call(
        api.POST("/cases/{case_id}/findings", {
          params: { path: { case_id: caseId } },
          body: { claim, evidence_ids: selected },
        }),
      );
      setClaim("");
      setSelected([]);
      onCreated();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <form onSubmit={submit} className="space-y-3">
        <h2 className="font-medium text-white">New finding</h2>
        <ErrorBanner error={error} />
        <Field label="Claim" hint="State only what the cited evidence shows. Allegations are not proof.">
          <Textarea required minLength={10} value={claim} onChange={(e) => setClaim(e.target.value)} />
        </Field>
        <Field label="Supporting evidence">
          <EvidencePicker evidence={evidence} refs={refs} selected={selected} onChange={setSelected} />
        </Field>
        <Button type="submit" busy={busy}>
          Save draft
        </Button>
      </form>
    </Card>
  );
}

function FindingCard({
  finding,
  me,
  canEdit,
  names,
  refs,
  evidence,
  onChange,
}: {
  finding: Finding;
  me: Me;
  canEdit: boolean;
  names: Map<string, string>;
  refs: Map<string, string>;
  evidence: Evidence[];
  onChange: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [claim, setClaim] = useState(finding.claim);
  const [selected, setSelected] = useState<string[]>(finding.evidence_ids ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const isAuthor = finding.author_id === me.id;
  const canReview = me.role === "reviewer" && !isAuthor && finding.status === "in_review";
  const path = { params: { path: { finding_id: finding.id } } };

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setEditing(false);
      onChange();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatusBadge status={finding.status} />
        <span className="text-xs text-zinc-500">
          by {names.get(finding.author_id) ?? "former member"} · {formatDate(finding.created_at)}
        </span>
      </div>
      {editing ? (
        <div className="mt-3 space-y-3">
          <Textarea value={claim} onChange={(e) => setClaim(e.target.value)} />
          <EvidencePicker evidence={evidence} refs={refs} selected={selected} onChange={setSelected} />
        </div>
      ) : (
        <p className="mt-3 whitespace-pre-wrap text-zinc-100">{finding.claim}</p>
      )}
      <p className="mt-2 text-xs text-zinc-500">
        Evidence: {(finding.evidence_ids ?? []).map((id) => refs.get(id) ?? "?").join(", ")}
      </p>
      {finding.review_note && (
        <p className={`mt-2 text-sm ${finding.status === "rejected" ? "text-red-300" : "text-zinc-300"}`}>
          {finding.status === "rejected" ? "Rejected: " : "Review note: "}
          {finding.review_note}
          {finding.reviewer_id && ` — ${names.get(finding.reviewer_id) ?? "reviewer"}`}
        </p>
      )}
      <ErrorBanner error={error} />
      <div className="mt-3 flex flex-wrap gap-2">
        {isAuthor && canEdit && (finding.status === "draft" || finding.status === "rejected") && (
          <>
            {editing ? (
              <Button
                busy={busy}
                onClick={() =>
                  run(() => call(api.PATCH("/findings/{finding_id}", { ...path, body: { claim, evidence_ids: selected } })))
                }
              >
                Save
              </Button>
            ) : (
              <Button variant="secondary" onClick={() => setEditing(true)}>
                {finding.status === "rejected" ? "Revise" : "Edit"}
              </Button>
            )}
            {finding.status === "draft" && !editing && (
              <Button busy={busy} onClick={() => run(() => call(api.POST("/findings/{finding_id}/submit", path)))}>
                Submit for review
              </Button>
            )}
          </>
        )}
        {canReview && (
          <>
            <Button
              busy={busy}
              onClick={() => {
                const note = window.prompt("Optional review note") ?? undefined;
                run(() => call(api.POST("/findings/{finding_id}/verify", { ...path, body: { note } })));
              }}
            >
              Verify
            </Button>
            <Button
              variant="danger"
              busy={busy}
              onClick={() => {
                const reason = window.prompt("Reason for rejection (required)");
                if (reason) run(() => call(api.POST("/findings/{finding_id}/reject", { ...path, body: { reason } })));
              }}
            >
              Reject
            </Button>
          </>
        )}
      </div>
    </Card>
  );
}
