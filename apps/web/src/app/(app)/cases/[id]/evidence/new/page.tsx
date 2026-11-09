import { AddEvidence } from "./add-evidence";

export default async function AddEvidencePage(props: PageProps<"/cases/[id]/evidence/new">) {
  const { id } = await props.params;
  return <AddEvidence caseId={id} />;
}
