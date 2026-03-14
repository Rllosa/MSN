interface Props {
  platform: string;
}

const PLATFORM_CONFIG: Record<
  string,
  { bg: string; text: string; label: string; img?: string }
> = {
  airbnb: { bg: "#FF5A5F", text: "#fff", label: "A", img: "/icons/airbnb.png" },
  booking: { bg: "#003580", text: "#fff", label: "B", img: "/icons/booking.svg" },
  whatsapp: { bg: "#25D366", text: "#fff", label: "W", img: "/icons/whatsapp.png" },
  direct: { bg: "#52525b", text: "#fff", label: "D" },
};

export default function PlatformIcon({ platform }: Props) {
  const config = PLATFORM_CONFIG[platform] ?? {
    bg: "#52525b",
    text: "#fff",
    label: platform.charAt(0).toUpperCase(),
  };

  if (config.img) {
    return (
      <img
        src={config.img}
        alt={platform}
        className="w-8 h-8 rounded-full shrink-0 object-cover"
      />
    );
  }

  return (
    <span
      style={{ background: config.bg, color: config.text }}
      className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
    >
      {config.label}
    </span>
  );
}
