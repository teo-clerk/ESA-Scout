import Dashboard from "@/components/Dashboard";
import EmptyState from "@/components/EmptyState";
import { loadSnapshot } from "@/lib/data";

// The snapshot is rewritten out-of-band by the agent, so render per request.
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function Page() {
  const { snapshot, error } = await loadSnapshot();

  if (!snapshot.opportunities.length) {
    return <EmptyState error={error} generatedAt={snapshot.generated_at} />;
  }

  return <Dashboard snapshot={snapshot} loadError={error} />;
}
