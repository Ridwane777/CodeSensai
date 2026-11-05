import { end, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const fallback: Scenario = {
  id: 'fallback',
  steps: [
    start(T),
    think(T, 's1', "Je n'ai pas de piste précise pour cette demande : je propose des exemples."),
    ...say(
      T,
      "Je ne suis pas sûr d'avoir bien compris. Je sais par exemple chercher dans le code du projet, écrire et tester une fonction, préparer un déploiement, chercher sur le web ou résumer la séance. Dis-moi ce que tu veux faire !",
    ),
    end(T),
  ],
}
