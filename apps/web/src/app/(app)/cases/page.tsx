"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { homeFor } from "@/components/app-shell";
import {
  Badge,
  EmptyState,
  ErrorBanner,
  Input,
  LinkButton,
  Loading,
  PageHeader,
  Select,
  StatusBadge,
} from "@/components/ui";
import {
  api,
  call,
  CATEGORY_LABELS,
  formatDate,
  STATUS_LABELS,
  type CaseCategory,
  type CaseStatus,
} from "@/lib/api";
import { isCasework, useMe, useQuery } from "@/lib/hooks";

export default function CasesPage() {
  const router = useRouter();
  const { data: me } = useMe();
  const [status, setStatus] = useState<CaseStatus | "">("");
  const [category, setCategory] = useState<CaseCategory | "">("");
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [mine, setMine] = useState(false);
  const [offset, setOffset] = useState(0);
  const limit = 25;

  useEffect(() => {
    if (me && !isCasework(me)) router.replace(homeFor(me.role));
  }, [me, router]);

  useEffect(() => {
    const t = setTimeout(() => setSearch(q), 300);
    return () => clearTimeout(t);
  }, [q]);

  const cases = useQuery(isCasework(me) ? ["cases", status, category, search, mine, offset] : null, () =>
    call(
      api.GET("/cases", {
        params: {
          query: {
            status: status || undefined,
            category: category || undefined,
            q: search || undefined,
            mine,
            limit,
            offset,
          },
        },
      }),
    ),
  );

  return (
    <>
      <PageHeader
        title="Cases"
        subtitle="Scam infrastructure under investigation in your organisation."
        actions={<LinkButton href="/cases/new" variant="primary">New case</LinkButton>}
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-[1fr_auto_auto_auto]">
        <Input
          type="search"
          placeholder="Search title or description…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOffset(0);
          }}
          aria-label="Search cases"
        />
        <Select
          aria-label="Filter by status"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as CaseStatus | "");
            setOffset(0);
          }}
        >
          <option value="">All statuses</option>
          {Object.entries(STATUS_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Filter by category"
          value={category}
          onChange={(e) => {
            setCategory(e.target.value as CaseCategory | "");
            setOffset(0);
          }}
        >
          <option value="">All categories</option>
          {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} className="accent-emerald-500" />
          Led by me
        </label>
      </div>
      <ErrorBanner error={cases.error} />
      {cases.isLoading && <Loading />}
      {cases.data && cases.data.items.length === 0 && (
        <EmptyState title="No cases match">Create a case to start collecting evidence.</EmptyState>
      )}
      {cases.data && cases.data.items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-zinc-900 text-xs text-zinc-400 uppercase">
              <tr>
                <th className="px-4 py-3 font-medium">Case</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Lead</th>
                <th className="px-4 py-3 font-medium">Evidence</th>
                <th className="px-4 py-3 font-medium">Findings</th>
                <th className="px-4 py-3 font-medium">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {cases.data.items.map((c) => (
                <tr key={c.id} className="hover:bg-zinc-900/60">
                  <td className="px-4 py-3">
                    <Link href={`/cases/${c.id}`} className="font-medium text-white hover:text-emerald-300">
                      {c.title}
                    </Link>
                    <div className="text-xs text-zinc-500">{CATEGORY_LABELS[c.category]}</div>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={c.status} label={STATUS_LABELS[c.status]} />
                  </td>
                  <td className="px-4 py-3 text-zinc-300">{c.lead_name}</td>
                  <td className="px-4 py-3 text-zinc-300">{c.evidence_count}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {c.finding_counts?.verified ? <Badge tone="green">{c.finding_counts.verified} verified</Badge> : null}
                      {c.finding_counts?.in_review ? <Badge tone="violet">{c.finding_counts.in_review} in review</Badge> : null}
                      {c.finding_counts?.draft ? <Badge>{c.finding_counts.draft} draft</Badge> : null}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs whitespace-nowrap text-zinc-500">{formatDate(c.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {cases.data && cases.data.total > limit && (
        <div className="mt-4 flex items-center justify-between text-sm text-zinc-400">
          <span>
            {offset + 1}–{Math.min(offset + limit, cases.data.total)} of {cases.data.total}
          </span>
          <div className="flex gap-2">
            <button disabled={offset === 0} onClick={() => setOffset(offset - limit)} className="disabled:opacity-40">
              ← Previous
            </button>
            <button
              disabled={offset + limit >= cases.data.total}
              onClick={() => setOffset(offset + limit)}
              className="disabled:opacity-40"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </>
  );
}
