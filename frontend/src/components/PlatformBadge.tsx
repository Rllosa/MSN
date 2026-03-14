interface Props {
  platform: string;
}

const PLATFORM_STYLES: Record<string, { label: string; className: string }> = {
  airbnb: { label: "Airbnb", className: "bg-rose-900/60 text-rose-300" },
  booking: { label: "Booking", className: "bg-blue-900/60 text-blue-300" },
  whatsapp: {
    label: "WhatsApp",
    className: "bg-emerald-900/60 text-emerald-300",
  },
  direct: { label: "Direct", className: "bg-zinc-700 text-zinc-300" },
};

export default function PlatformBadge({ platform }: Props) {
  const style = PLATFORM_STYLES[platform] ?? {
    label: platform,
    className: "bg-zinc-700 text-zinc-300",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${style.className}`}
    >
      {style.label}
    </span>
  );
}
