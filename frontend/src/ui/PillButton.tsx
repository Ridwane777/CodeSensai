import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Link } from 'react-router-dom'

interface Props extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  variant?: 'solid' | 'outline'
  to?: string
  arrow?: boolean
  children: ReactNode
}

const base =
  'inline-flex items-center justify-center gap-2 rounded-full px-5 py-2.5 text-[15px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50'
const styles = {
  solid: 'bg-accent-strong text-accent-contrast hover:brightness-110',
  outline: 'border border-line bg-surface/60 text-ink hover:bg-accent-soft',
}

export function PillButton({ variant = 'solid', to, arrow, children, className = '', ...rest }: Props) {
  const cls = `${base} ${styles[variant]} ${className}`
  const content = (
    <>
      {children}
      {(arrow ?? variant === 'solid') && <span aria-hidden="true">→</span>}
    </>
  )
  if (to) {
    return (
      <Link to={to} className={cls}>
        {content}
      </Link>
    )
  }
  return (
    <button type="button" className={cls} {...rest}>
      {content}
    </button>
  )
}
