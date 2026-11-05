import { budget } from './budget'
import { fallback } from './fallback'
import { fix } from './fix'
import { form } from './form'
import { resume } from './resume'
import { risky } from './risky'
import { search } from './search'
import { secret } from './secret'
import type { Scenario } from './types'
import { web } from './web'
import { wrapup } from './wrapup'

export const SCENARIOS: Record<string, Scenario> = {
  resume, search, fix, risky, secret, form, web, budget, wrapup, fallback,
}
