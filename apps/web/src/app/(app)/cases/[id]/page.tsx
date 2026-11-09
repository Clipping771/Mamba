import { CaseView } from "./case-view";

export default async function CasePage(props: PageProps<"/cases/[id]">) {
  const { id } = await props.params;
  return <CaseView id={id} />;
}
