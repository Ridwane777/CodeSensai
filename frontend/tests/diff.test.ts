import { diffLines } from '../src/ui/diff'

test('marque les lignes ajoutées, retirées et inchangées', () => {
  expect(diffLines('a\nb', 'a\nc')).toEqual([
    { mark: ' ', text: 'a' },
    { mark: '-', text: 'b' },
    { mark: '+', text: 'c' },
  ])
})

test('textes identiques ou vides', () => {
  expect(diffLines('a', 'a')).toEqual([{ mark: ' ', text: 'a' }])
  expect(diffLines('', '')).toEqual([{ mark: ' ', text: '' }])
})
