import { useMemo } from "react";

export type DatePreset = "today" | "last7" | "last30" | "year" | "custom";

export type DateRange = {
  preset: DatePreset;
  fromDate: string | null;
  toDate: string | null;
};

function isoUtcStartOfDay(dateStr: string) {
  const [y, m, d] = dateStr.split("-").map((v) => Number(v));
  return new Date(Date.UTC(y, m - 1, d, 0, 0, 0)).toISOString();
}

function isoUtcEndOfDay(dateStr: string) {
  const [y, m, d] = dateStr.split("-").map((v) => Number(v));
  return new Date(Date.UTC(y, m - 1, d, 23, 59, 59)).toISOString();
}

function todayIsoDate() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function addDaysIsoDate(dateStr: string, deltaDays: number) {
  const [y, m, d] = dateStr.split("-").map((v) => Number(v));
  const base = new Date(Date.UTC(y, m - 1, d, 0, 0, 0));
  base.setUTCDate(base.getUTCDate() + deltaDays);
  const yy = base.getUTCFullYear();
  const mm = String(base.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(base.getUTCDate()).padStart(2, "0");
  return `${yy}-${mm}-${dd}`;
}

export function buildPresetRange(preset: DatePreset): { from_date?: string; to_date?: string; fromDate: string; toDate: string } {
  const today = todayIsoDate();
  if (preset === "today") {
    return { from_date: isoUtcStartOfDay(today), to_date: isoUtcEndOfDay(today), fromDate: today, toDate: today };
  }
  if (preset === "last7") {
    const from = addDaysIsoDate(today, -6);
    return { from_date: isoUtcStartOfDay(from), to_date: isoUtcEndOfDay(today), fromDate: from, toDate: today };
  }
  if (preset === "last30") {
    const from = addDaysIsoDate(today, -29);
    return { from_date: isoUtcStartOfDay(from), to_date: isoUtcEndOfDay(today), fromDate: from, toDate: today };
  }
  if (preset === "year") {
    const from = `${new Date().getFullYear()}-01-01`;
    const to = `${new Date().getFullYear()}-12-31`;
    return { from_date: isoUtcStartOfDay(from), to_date: isoUtcEndOfDay(to), fromDate: from, toDate: to };
  }
  return { fromDate: today, toDate: today };
}

export function DateRangeControls(props: {
  range: DateRange;
  onChange: (next: DateRange) => void;
}) {
  const options = useMemo(
    () => [
      { value: "today", label: "Oggi" },
      { value: "last7", label: "Ultimi 7 giorni" },
      { value: "last30", label: "Ultimi 30 giorni" },
      { value: "year", label: "Anno corrente" },
      { value: "custom", label: "Personalizzato" },
    ],
    [],
  );

  return (
    <div className="row">
      <select
        className="auth-input"
        value={props.range.preset}
        onChange={(e) => props.onChange({ ...props.range, preset: e.target.value as DatePreset })}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>

      {props.range.preset === "custom" ? (
        <>
          <input
            className="auth-input"
            type="date"
            value={props.range.fromDate ?? ""}
            onChange={(e) => props.onChange({ ...props.range, fromDate: e.target.value || null })}
          />
          <input
            className="auth-input"
            type="date"
            value={props.range.toDate ?? ""}
            onChange={(e) => props.onChange({ ...props.range, toDate: e.target.value || null })}
          />
        </>
      ) : null}
    </div>
  );
}

export function toApiRange(range: DateRange): { from_date?: string; to_date?: string } {
  if (range.preset === "custom") {
    if (!range.fromDate || !range.toDate) return {};
    return { from_date: isoUtcStartOfDay(range.fromDate), to_date: isoUtcEndOfDay(range.toDate) };
  }
  const preset = buildPresetRange(range.preset);
  return { from_date: preset.from_date, to_date: preset.to_date };
}
