"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button, Card, ErrorBanner, Field, Input, LinkButton, PageHeader, Select, Tabs, Textarea } from "@/components/ui";
import { api, call, CSRF_HEADERS, toApiError } from "@/lib/api";
import { useInvalidate } from "@/lib/hooks";

type Mode = "file" | "url" | "note";

export function AddEvidence({ caseId }: { caseId: string }) {
  const router = useRouter();
  const invalidate = useInvalidate();
  const [mode, setMode] = useState<Mode>("file");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileType, setFileType] = useState<"file" | "screenshot">("file");
  const [sourceUrl, setSourceUrl] = useState("");
  const [url, setUrl] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const back = `/cases/${caseId}`;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "file") {
        if (!file) throw new Error("Choose a file.");
        const form = new FormData();
        form.append("file", file);
        form.append("type", fileType);
        form.append("title", title);
        form.append("description", description);
        if (sourceUrl) form.append("source_url", sourceUrl);
        const response = await fetch(`/api/bm/cases/${caseId}/evidence/file`, {
          method: "POST",
          headers: CSRF_HEADERS,
          body: form,
        });
        if (!response.ok) throw toApiError(response.status, await response.json().catch(() => ({})));
      } else if (mode === "url") {
        await call(
          api.POST("/cases/{case_id}/evidence/url", {
            params: { path: { case_id: caseId } },
            body: { url, title, description },
          }),
        );
      } else {
        await call(
          api.POST("/cases/{case_id}/evidence/note", {
            params: { path: { case_id: caseId } },
            body: { title, body },
          }),
        );
      }
      await invalidate(caseId, "cases");
      router.push(back);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Add evidence"
        subtitle="Evidence is hashed (SHA-256) when captured and can never be edited or deleted, only excluded with a reason."
      />
      <Card className="max-w-2xl">
        <Tabs<Mode>
          active={mode}
          onChange={setMode}
          tabs={[
            { id: "file", label: "Upload file" },
            { id: "url", label: "Record URL" },
            { id: "note", label: "Written observation" },
          ]}
        />
        <form onSubmit={submit} className="space-y-4">
          <ErrorBanner error={error} />
          <Field label="Title">
            <Input
              required={mode === "note"}
              maxLength={300}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={mode === "file" ? "Defaults to the file name" : ""}
            />
          </Field>
          {mode === "file" && (
            <>
              <Field label="File" hint="Screenshots, exported chats, PDFs, emails (.eml)… up to 50 MB.">
                <Input type="file" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </Field>
              <Field label="Kind">
                <Select value={fileType} onChange={(e) => setFileType(e.target.value as "file" | "screenshot")}>
                  <option value="file">File</option>
                  <option value="screenshot">Screenshot</option>
                </Select>
              </Field>
              <Field label="Where it came from (optional)">
                <Input type="url" placeholder="https://…" value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} />
              </Field>
            </>
          )}
          {mode === "url" && (
            <Field
              label="URL"
              hint="Records the address only. To preserve the page itself, use 'Archive a URL' on the case."
            >
              <Input type="url" required value={url} onChange={(e) => setUrl(e.target.value)} />
            </Field>
          )}
          {mode === "note" ? (
            <Field label="Observation" hint="What you saw, where, and when. Stored and hashed like a file.">
              <Textarea required rows={8} value={body} onChange={(e) => setBody(e.target.value)} />
            </Field>
          ) : (
            <Field label="Description (optional)">
              <Textarea value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>
          )}
          <div className="flex gap-2">
            <Button type="submit" busy={busy}>
              Save evidence
            </Button>
            <LinkButton href={back}>Cancel</LinkButton>
          </div>
        </form>
      </Card>
    </>
  );
}
