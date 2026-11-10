import { useState } from 'react'

type Theme = 'light' | 'dark'

function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem('sensai-theme')
    if (saved === 'light' || saved === 'dark') return saved
  } catch { /* stockage indisponible */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => {
    const t = initialTheme()
    document.documentElement.dataset.theme = t
    return t
  })

  function toggle() {
    const next: Theme = theme === 'light' ? 'dark' : 'light'
    setTheme(next)
    document.documentElement.dataset.theme = next
    try { localStorage.setItem('sensai-theme', next) } catch { /* ignored */ }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Change theme (currently ${theme === 'light' ? 'light' : 'dark'})`}
      className="grid h-10 w-10 place-items-center rounded-full border border-line bg-surface/60 text-lg hover:bg-accent-soft"
    >
      <span aria-hidden="true">{theme === 'light' ? '☾' : '☀'}</span>
    </button>
  )
}
