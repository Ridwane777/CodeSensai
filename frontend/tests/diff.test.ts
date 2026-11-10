import { diffLines } from '../src/ui/diff'

test('marks added, removed and unchanged lines', () => {
  expect(diffLines('a\nb', 'a\nc')).toEqual([
    { mark: ' ', text: 'a' },
    { mark: '-', text: 'b' },
    { mark: '+', text: 'c' },
  ])
})

test('identical or empty texts', () => {
  expect(diffLines('a', 'a')).toEqual([{ mark: ' ', text: 'a' }])
  expect(diffLines('', '')).toEqual([{ mark: ' ', text: '' }])
})
