export interface DiffLine {
  mark: ' ' | '+' | '-'
  text: string
}

/** Line-by-line diff (longest common subsequence). */
export function diffLines(a: string, b: string): DiffLine[] {
  const x = a.split('\n')
  const y = b.split('\n')
  const lcs: number[][] = Array.from({ length: x.length + 1 }, () => new Array(y.length + 1).fill(0))
  for (let i = x.length - 1; i >= 0; i--)
    for (let j = y.length - 1; j >= 0; j--)
      lcs[i][j] = x[i] === y[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
  const out: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) { out.push({ mark: ' ', text: x[i] }); i++; j++ }
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) out.push({ mark: '-', text: x[i++] })
    else out.push({ mark: '+', text: y[j++] })
  }
  while (i < x.length) out.push({ mark: '-', text: x[i++] })
  while (j < y.length) out.push({ mark: '+', text: y[j++] })
  return out
}
