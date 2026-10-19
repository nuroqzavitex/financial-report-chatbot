import { Sigma } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { citationLabel } from "@/lib/format";
import type { CalcDTO } from "@/lib/api/client";

export function CalcChip({ calc }: { calc: CalcDTO }) {
  const label = calc.rendered ?? calc.value ?? calc.id;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="bg-secondary hover:bg-pencil-wash hover:text-pencil aria-expanded:bg-pencil-wash aria-expanded:text-pencil focus-visible:ring-pencil/40 inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium outline-none focus-visible:ring-3"
        >
          <Sigma className="size-3.5" aria-hidden />
          {label}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[min(24rem,calc(100vw-2rem))] text-sm">
        <p className="font-serif text-base font-medium">{calc.rendered}</p>
        {calc.formula && (
          <code className="bg-muted mt-1 inline-block rounded px-1.5 py-0.5 text-xs">
            {calc.formula}
          </code>
        )}
        <ul className="border-rule mt-3 divide-y divide-[var(--rule)] border-t text-xs">
          {calc.operands.map((o, i) => (
            <li
              key={`${o.fact_id}-${i}`}
              className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 py-2"
            >
              <span className="text-ink-soft">
                {[o.label, o.period].filter(Boolean).join(", ")}
              </span>
              <span className="text-right font-medium">
                {`${o.raw ?? o.value} ${o.unit}`}
              </span>
              <span className="text-pencil col-span-2">
                {citationLabel(o.printed_pages)}
              </span>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
