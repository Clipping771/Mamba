"use client";

import Link from "next/link";
import { useState } from "react";

import { Button, Card, EmptyState, ErrorBanner, Field, Loading, PageHeader, Textarea } from "@/components/ui";
import { api, call, formatDate, type ReviewItem } from "@/lib/api";
import { useInvalidate, useQuery } from "@/lib/hooks";

export default function ReviewPage() {
  const queue = useQuery(["review-queue"], () => call(api.GET("/findings/review-queue")));
  return (
    <>
      <PageHeader
        title="Review queue"
        subtitle="Findings written by colleagues and awaiting an independent check. Your own findings are never shown here."
      />
      <ErrorBanner error={queue.error} />
      {queue.isLoading && <Loading />}
      {queue.data?.length === 0 && <EmptyState title="Nothing to review">All caught up.</EmptyState>}
      <div className="space-y-4">
        {queue.data?.map((item) => (
          <ReviewCard key={item.id} item={item} onDone={() => queue.mutate()} />
        ))}
      </div>
    </>
  );
}

function ReviewCard({ item, onDone }: { item: ReviewItem; onDone: () => void }) {
  const invalidate = useInvalidate();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const path = { params: { path: { finding_id: item.id } } };

  async function decide(kind: "verify" | "reject") {
    if (kind === "reject" && note.trim().length < 5) {
      setError(new Error("Explain why the finding is rejected (at least 5 characters)."));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (kind === "verify") {
        await call(api.POST("/findings/{finding_id}/verify", { ...path, body: { note: note || undefined } }));
      } else {
        await call(api.POST("/findings/{finding_id}/reject", { ...path, body: { reason: note } }));
      }
      await invalidate(item.case_id, "cases");
      onDone();
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-zinc-500">
        <Link href={`/cases/${item.case_id}`} className="text-sm text-emerald-400 hover:text-emerald-300">
          {item.case_title}
        </Link>
        <span>
          by {item.author_name} · submitted {formatDate(item.submitted_at)}
        </span>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-zinc-100">{item.claim}</p>
      <p className="mt-2 text-xs text-zinc-500">
        Cites {item.evidence_ids?.length ?? 0} evidence item(s). Open the case to check each one (and verify its
        hash) before deciding.
      </p>
      <div className="mt-4 space-y-3">
        <ErrorBanner error={error} />
        <Field label="Review note" hint="Optional when verifying, required when rejecting.">
          <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <div className="flex gap-2">
          <Button busy={busy} onClick={() => decide("verify")}>
            Verify
          </Button>
          <Button variant="danger" busy={busy} onClick={() => decide("reject")}>
            Reject
          </Button>
        </div>
      </div>
    </Card>
  );
}
