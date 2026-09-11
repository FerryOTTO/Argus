/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'mimo': {
          bg: '#FAFAF8',
          card: '#FFFFFF',
          cardHover: '#F4F4F0',
          border: 'rgba(0, 0, 0, 0.06)',
          orange: '#FF6900',
          orangeHover: '#FF8533',
          orangeDim: 'rgba(255, 105, 0, 0.08)',
          cyan: '#0891B2',
          emerald: '#059669',
          crimson: '#DC2626'
        }
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', '"PingFang SC"', '"Hiragino Sans GB"', '"Microsoft YaHei"', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', '"Cascadia Code"', '"Fira Code"', 'Consolas', 'monospace'],
      },
      boxShadow: {
        'mimo-glow': '0 0 24px rgba(255, 105, 0, 0.25)',
        'mimo-glow-sm': '0 0 12px rgba(255, 105, 0, 0.18)',
        'card-glow': '0 8px 32px 0 rgba(0, 0, 0, 0.06)',
      }
    },
  },
  plugins: [],
}