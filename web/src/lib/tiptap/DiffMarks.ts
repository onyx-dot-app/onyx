import { Mark } from '@tiptap/core'

export const DeletionMark = Mark.create({
  name: 'deletionMark',
  
  // Define the HTML tag that will be used
  // This corresponds to our <deletion-mark> tag
  parseHTML() {
    return [
      {
        tag: 'deletion-mark',
      },
    ]
  },
  
  // Define how this mark will be rendered in HTML
  renderHTML({ HTMLAttributes }) {
    return ['deletion-mark', HTMLAttributes, 0]
  },
})

export const AdditionMark = Mark.create({
  name: 'additionMark',
  
  // Define the HTML tag that will be used
  // This corresponds to our <addition-mark> tag
  parseHTML() {
    return [
      {
        tag: 'addition-mark',
      },
    ]
  },
  
  // Define how this mark will be rendered in HTML
  renderHTML({ HTMLAttributes }) {
    return ['addition-mark', HTMLAttributes, 0]
  },
})
