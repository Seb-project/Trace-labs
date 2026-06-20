/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      boxShadow: {
        glow: "0 0 40px rgba(168, 85, 247, 0.16)"
      },
      colors: {
        pcb: {
          panel: "rgba(15, 23, 42, 0.62)",
          border: "rgba(148, 163, 184, 0.22)",
          orange: "#f97316",
          purple: "#a855f7"
        }
      }
    }
  },
  plugins: []
};
