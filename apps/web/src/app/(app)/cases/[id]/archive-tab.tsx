"use client";

import { useRef, useState, type FormEvent } from "react";

import { Button, Card, EmptyState, ErrorBanner, Field, Input, Loading, Mono, StatusBadge } from "@/components/ui";
import { api, call, formatDate, type ArchiveJob } from "@/lib/api";
import { useQuery } from "@/lib/hooks";

export function ArchiveTab({ caseId, canEdit, onDone }: { caseId: string; canEdit: boolean; onDone: () => void }) {
  const finished = useRef(new Set<string>());
  const jobs = useQuery(
    ["archive-jobs", caseId],
    () => call(api.GET("/cases/{case_id}/archive-jobs", { params: { path: { case_id: caseId } } })),
    {
      // Poll while any job is still queued or running.
      refreshInterval: (data?: ArchiveJob[]) =>
        data?.some((j) => j.status === "queued" || j.status === "running") ? 2500 : 0,
      onSuccess: (data: ArchiveJob[]) => {
        let changed = false;
        for (const job of data) {
          if (job.status === "done" && !finished.current.has(job.id)) {
            finished.current.add(job.id);
            changed = true;
          }
        }
        if (changed) onDone();
      },
    },
  );
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await call(api.POST("/cases/{case_id}/archive", { params: { path: { case_id: caseId } }, body: { url } }));
      setUrl("");
      await jobs.mutate();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      {canEdit && (
        <Card>
          <form onSubmit={submit} className="space-y-3">
            <Field
              label="Public URL to archive"
              hint="A sandboxed browser opens the page once: no login, no form submission, no clicking. It captures a full-page screenshot, the HTML, the final URL, the HTTP status and a UTC timestamp, all hashed as evidence."
            >
              <Input
                type="url"
                required
                placeholder="https://suspicious-site.example/offer"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
            </Field>
            <ErrorBanner error={error} />
            <Button type="submit" busy={busy}>
              Archive page
            </Button>
          </form>
        </Card>
      )}
      {jobs.isLoading && <Loading />}
      {jobs.data && jobs.data.length === 0 && <EmptyState title="No archive jobs yet" />}
      <div className="space-y-2">
        {jobs.data?.map((job) => (
          <div key={job.id} className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={job.status} />
              <Mono className="text-zinc-300">{job.url}</Mono>
            </div>
            <div className="mt-1 text-xs text-zinc-500">
              Requested {formatDate(job.created_at)}
              {job.finished_at && ` · finished ${formatDate(job.finished_at)}`}
              {job.status === "done" && ` · ${job.evidence_ids?.length ?? 0} evidence items added`}
            </div>
            {job.error && <p className="mt-2 text-sm text-red-300">{job.error}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}
