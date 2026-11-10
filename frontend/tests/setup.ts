import '@testing-library/jest-dom/vitest'
import { beforeEach } from 'vitest'

// Some UI choices are kept in localStorage (open panel, token…):
// each test starts from empty storage, otherwise a test inherits the previous one's state.
beforeEach(() => {
  try {
    localStorage.clear()
  } catch {
    /* storage unavailable: nothing to clear */
  }
})
