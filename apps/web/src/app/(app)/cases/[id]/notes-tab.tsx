"use client";

import { useState, type FormEvent } from "react";

import { AiDraftBadge, Button, Card, EmptyState, ErrorBanner, Loading, Textarea } from "@/components/ui";
import { api, call, formatDate } from "@/lib/api";
import { useQuery } from "@/lib/hooks";

export function NotesTab({ caseId, canEdit, names }: { caseId: string; canEdit: boolean; names: Map<string, string> }) {
  const notes = useQuery(["notes", caseId], () =>
    call(api.GET("/cases/{case_id}/notes", { params: { path: { case_id: caseId } } })),
  );
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [agentBusy, setAgentBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function addNote(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await call(api.POST("/cases/{case_id}/notes", { params: { path: { case_id: caseId } }, body: { body } }));
      setBody("");
      await notes.mutate();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function runArchivist() {
    setAgentBusy(true);
    setError(null);
    try {
      await call(api.POST("/cases/{case_id}/archivist", { params: { path: { case_id: caseId } } }));
      await notes.mutate();
    } catch (err) {
      setError(err);
    } finally {
      setAgentBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <ErrorBanner error={error} />
      {canEdit && (
        <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
          <Card>
            <form onSubmit={addNote} className="space-y-3">
              <h2 className="font-medium text-white">Working note</h2>
              <Textarea
                required
                placeholder="Leads, open questions, next steps… (not evidence; use 'Add evidence' for observations to preserve)"
                value={body}
                onChange={(e) => setBody(e.target.value)}
              />
              <Button type="submit" busy={busy}>
                Add note
              </Button>
            </form>
          </Card>
          <Card>
            <h2 className="font-medium text-white">ARCHIVIST agent</h2>
            <p className="mt-1 text-sm text-zinc-400">
              Drafts a summary and timeline from evidence metadata and human notes. Output is labelled
              <span className="mx-1 text-amber-300">AI draft — not verified</span>and never appears in reports.
            </p>
            <Button className="mt-3" variant="secondary" busy={agentBusy} onClick={runArchivist}>
              {agentBusy ? "Drafting…" : "Run ARCHIVIST"}
            </Button>
          </Card>
        </div>
      )}
      {notes.isLoading && <Loading />}
      {notes.data && notes.data.length === 0 && <EmptyState title="No notes yet" />}
      <div className="space-y-3">
        {notes.data?.map((note) => (
          <Card key={note.id} className={note.is_ai_draft ? "border-amber-500/30 bg-amber-500/5" : undefined}>
            <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
              {note.is_ai_draft && <AiDraftBadge />}
              <span>
                {note.is_ai_draft ? `Requested by ${names.get(note.author_id) ?? "member"} · ${note.ai_model}` : names.get(note.author_id) ?? "member"}
              </span>
              <span>· {formatDate(note.created_at)}</span>
            </div>
            <p className="text-sm whitespace-pre-wrap text-zinc-200">{note.body}</p>
          </Card>
        ))}
      </div>
    </div>
  );
}
