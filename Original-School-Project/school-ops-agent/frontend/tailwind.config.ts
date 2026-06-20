import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#1B2A2F",
        paper: "#F7F4EC",
        surface: "#FFFFFF",
        accent: "#2F6F6A",
        "accent-dark": "#24544F",
        blocked: "#B4541E",
        ok: "#3E7B4F",
        muted: "#6B7670",
        line: "#E4DFD3",
      },
      fontFamily: {
        display: ['Fraunces', 'Georgia', 'serif'],
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Inter', 'sans-serif'],
        mono: ['ui-monospace', 'SF Mono', 'Menlo', 'monospace'],
      },
      boxShadow: {
        card: "0 1px 2px rgba(27,42,47,0.06), 0 4px 12px rgba(27,42,47,0.04)",
      },
      keyframes: {
        slidein: {
          "0%": { opacity: "0", transform: "translateY(-6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: { slidein: "slidein 0.25s ease-out" },
    },
  },
  plugins: [],
};
export default config;
