export function bindExploration(root: HTMLElement) {
  for (const panel of root.querySelectorAll<HTMLElement>('[data-explore]')) {
    const detail = panel.querySelector<HTMLElement>('[data-explore-detail]')!
    const summary = detail.textContent
    let pinned: HTMLElement | SVGElement | undefined

    for (const mark of panel.querySelectorAll<HTMLElement | SVGElement>('[data-detail]')) {
      const show = () => { detail.textContent = mark.dataset.detail! }
      const restore = () => { detail.textContent = pinned?.dataset.detail ?? summary }

      mark.addEventListener('pointerenter', show)
      mark.addEventListener('pointerleave', restore)
      mark.addEventListener('focus', show)
      mark.addEventListener('blur', restore)
      mark.addEventListener('click', () => {
        const next = pinned === mark ? undefined : mark
        pinned?.setAttribute('aria-pressed', 'false')
        pinned = next
        pinned?.setAttribute('aria-pressed', 'true')
        restore()
      })
      if (mark instanceof SVGElement) {
        mark.addEventListener('keydown', event => {
          const key = (event as KeyboardEvent).key
          if (key === 'Enter' || key === ' ') {
            event.preventDefault()
            mark.dispatchEvent(new MouseEvent('click'))
          }
        })
      }
    }
    panel.addEventListener('keydown', event => {
      if (event.key === 'Escape' && pinned) {
        pinned.setAttribute('aria-pressed', 'false')
        pinned = undefined
        detail.textContent = summary
      }
    })
  }
}
