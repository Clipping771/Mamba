import { ReportView } from "./report-view";

export default async function ReportPage(props: PageProps<"/cases/[id]/report">) {
  const { id } = await props.params;
  return <ReportView caseId={id} />;
}
