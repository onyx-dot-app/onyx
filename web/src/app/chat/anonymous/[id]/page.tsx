export default async function Page(props: { params: Promise<{ id: string }> }) {
  const params = await props.params;
  const tenantId = params.id;

  return (
    <div>
      <h1>Anonymous User</h1>
      {tenantId}
    </div>
  );
}
