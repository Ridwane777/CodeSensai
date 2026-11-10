/**
 * Logo: a striped orange disc, echoing the AI visor. The former floating header gave way
 * to the sidebar (`Sidebar`); the file keeps the logo, imported elsewhere.
 */
export function BrandMark({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="2" />
      <path d="M9 4.6v14.8M12 3v18M15 4.6v14.8" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}
