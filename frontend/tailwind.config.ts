import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}", "./components/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: { extend: { colors: { ink: "#080a12", panel: "#10131f", muted: "#9298ad" }, boxShadow: { glow: "0 0 60px rgba(112, 83, 255, 0.16)" } } },
  plugins: [],
};
export default config;
