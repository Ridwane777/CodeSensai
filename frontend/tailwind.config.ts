import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        surface: 'var(--surface-solid)',
        ink: 'var(--text)',
        muted: 'var(--muted)',
        line: 'var(--border)',
        accent: 'var(--accent)',
        'accent-strong': 'var(--accent-strong)',
        'accent-contrast': 'var(--accent-contrast)',
        'accent-soft': 'var(--accent-soft)',
        ok: 'var(--ok)',
        warn: 'var(--warn)',
        danger: 'var(--danger)',
        'hero-text': 'var(--hero-text)',
        'hero-muted': 'var(--hero-muted)',
        'hero-cta': 'var(--hero-cta)',
      },
      fontFamily: { sans: ["'Plus Jakarta Sans Variable'", 'system-ui', 'sans-serif'] },
    },
  },
  plugins: [],
} satisfies Config
