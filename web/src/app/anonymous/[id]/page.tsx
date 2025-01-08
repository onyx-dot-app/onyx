import AnonymousPage from "./AnonymousPage";

export default async function Page(props: { params: Promise<{ id: string }> }) {
  const params = await props.params;

  return <AnonymousPage anonymousPath={params.id} />;
}
