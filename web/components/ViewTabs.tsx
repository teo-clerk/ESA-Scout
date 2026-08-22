"use client";

/** Switches between the two scouting surfaces: ESA opportunities and SMEs. */

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/", label: "ESA Opportunities" },
  { href: "/sme", label: "SME Internship Targets (ES/IT)" },
];

export default function ViewTabs() {
  const pathname = usePathname();

  return (
    <nav aria-label="Views" className="flex gap-1">
      {TABS.map((tab) => {
        const active = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
              active
                ? "bg-[--color-panel-raised] text-slate-100 ring-1 ring-[--color-edge]"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
