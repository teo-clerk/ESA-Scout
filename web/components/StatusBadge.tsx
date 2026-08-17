import { STATUS_STYLES } from "@/lib/format";
import type { Status } from "@/lib/types";

export default function StatusBadge({ status }: { status: Status }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${
        STATUS_STYLES[status] ?? STATUS_STYLES.Unknown
      }`}
    >
      {status}
    </span>
  );
}
