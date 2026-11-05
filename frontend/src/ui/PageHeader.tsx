export function PageHeader({ title, intro }: { title: string; intro: string }) {
  return (
    <header className="mb-6 pt-4">
      <h1 className="text-4xl font-extrabold tracking-tight">{title}</h1>
      <p className="mt-2 max-w-2xl text-muted">{intro}</p>
    </header>
  )
}
