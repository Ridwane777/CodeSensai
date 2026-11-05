import '@testing-library/jest-dom/vitest'
import { beforeEach } from 'vitest'

// Certains choix de l'interface sont gardés dans localStorage (panneau ouvert, jeton…) :
// chaque test repart d'un stockage vide, sinon un test hérite de l'état du précédent.
beforeEach(() => {
  try {
    localStorage.clear()
  } catch {
    /* stockage indisponible : rien à vider */
  }
})
