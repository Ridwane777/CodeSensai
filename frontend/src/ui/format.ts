export const fmt = (n: number) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
export const pct = (x: number) => `${Math.round(x * 100)} %`
