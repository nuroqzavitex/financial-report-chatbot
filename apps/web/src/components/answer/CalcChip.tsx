import { Button } from "@/components/ui/button";
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
        <Button type="button" variant="secondary" size="xs">
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-96 text-sm">
        <p className="font-medium">{calc.rendered}</p>
        {calc.formula && (
          <code className="bg-muted rounded px-1.5 py-0.5 text-xs">
            {calc.formula}
          </code>
        )}
        <ul className="text-muted-foreground mt-2 space-y-1 text-xs">
          {calc.operands.map((o, i) => (
            <li key={`${o.fact_id}-${i}`}>
              {[o.label, o.period, `${o.raw ?? o.value} ${o.unit}`]
                .filter(Boolean)
                .join(" · ")}{" "}
              · {citationLabel(o.printed_pages)}
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
