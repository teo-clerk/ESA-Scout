import SmeView from "@/components/SmeView";
import { loadSmeSnapshot } from "@/lib/sme-data";

import type { Metadata } from "next";

// The snapshot is rewritten out-of-band by the agent, so render per request.
export const dynamic = "force-dynamic";
export const revalidate = 0;

export const metadata: Metadata = {
  title: "SME Internship Targets · ESA Scout",
  description:
    "ESA-registered space SMEs in Spain and Italy, ranked as speculative " +
    "summer internship targets against your CV and GitHub activity.",
};

export default async function SmePage() {
  const { snapshot, error } = await loadSmeSnapshot();
  return <SmeView initialSnapshot={snapshot} loadError={error} />;
}
