/** Visual match-score meter. Renders an explicit unscored state at 0. */

import { matchTone } from "@/lib/format";

export default function MatchMeter({
  score,
  evaluated,
}: {
  score: number;
  /** False when the AI evaluator never ran, which is not the same as 0%. */
  evaluated: boolean;
}) {
  const tone = matchTone(score);

  if (!evaluated) {
    return (
      <div className="w-28 shrink-0 text-right">
        <span className="text-xs text-slate-600">Not scored</span>
      </div>
    );
  }

  return (
    <div className="w-28 shrink-0">
      <div className="flex items-baseline justify-end gap-1">
        <span className={`text-lg font-semibold tabular-nums ${tone.text}`}>
          {score}
        </span>
        <span className="text-xs text-slate-600">%</span>
      </div>
      <div
        className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-800"
        role="meter"
        aria-valuenow={score}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Match score"
      >
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${tone.bar}`}
          style={{ width: `${Math.max(2, Math.min(100, score))}%` }}
        />
      </div>
    </div>
  );
}
