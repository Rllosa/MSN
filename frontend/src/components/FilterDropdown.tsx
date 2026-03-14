import { useEffect, useRef, useState } from "react";

interface Item {
  value: string;
  label: string;
}

interface Props {
  label: string;
  items: Item[];
  selected: string[];
  onToggle: (value: string) => void;
  onClear: () => void;
}

export default function FilterDropdown({
  label,
  items,
  selected,
  onToggle,
  onClear,
}: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={`text-xs font-medium px-3 py-1 rounded-full transition-colors flex items-center gap-1 ${
          selected.length > 0
            ? "bg-blue-600 text-white"
            : "bg-zinc-800 text-zinc-400 hover:text-zinc-200"
        }`}
      >
        {label}
        {selected.length > 0 && (
          <span className="bg-white/20 rounded-full px-1.5">{selected.length}</span>
        )}
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1 bg-zinc-900 border border-white/10 rounded-lg shadow-xl z-10 py-1 min-w-[160px] max-h-64 overflow-y-auto">
          {items.map(({ value, label: itemLabel }) => {
            const checked = selected.includes(value);
            return (
              <button
                key={value}
                onClick={() => onToggle(value)}
                className="w-full flex items-center gap-2.5 px-3 py-2 text-xs text-zinc-300 hover:bg-white/5 transition-colors"
              >
                <span
                  className={`w-3.5 h-3.5 rounded border flex items-center justify-center shrink-0 ${
                    checked ? "bg-blue-600 border-blue-600" : "border-zinc-600"
                  }`}
                >
                  {checked && (
                    <svg
                      className="w-2.5 h-2.5 text-white"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={3}
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                  )}
                </span>
                {itemLabel}
              </button>
            );
          })}
          {selected.length > 0 && (
            <>
              <div className="border-t border-white/10 my-1" />
              <button
                onClick={() => {
                  onClear();
                  setOpen(false);
                }}
                className="w-full px-3 py-1.5 text-xs text-zinc-500 hover:text-zinc-300 transition-colors text-left"
              >
                Clear
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
