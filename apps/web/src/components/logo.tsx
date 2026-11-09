export function Logo({ size = "md" }: { size?: "md" | "lg" }) {
  const px = size === "lg" ? 36 : 26;
  return (
    <span className="inline-flex items-center gap-2">
      <svg width={px} height={px} viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="7" fill="#09090b" stroke="#34d399" strokeWidth="1.5" />
        <path
          d="M8 21c3-1 4-4 7-4s4 3 7 2 3-5 1-7-5-1-6 1"
          fill="none"
          stroke="#34d399"
          strokeWidth="2.2"
          strokeLinecap="round"
        />
        <circle cx="20.5" cy="12.5" r="1.2" fill="#34d399" />
      </svg>
      <span className={size === "lg" ? "text-xl font-semibold tracking-[0.18em]" : "text-sm font-semibold tracking-[0.18em]"}>
        BLACK MAMBA
      </span>
    </span>
  );
}
