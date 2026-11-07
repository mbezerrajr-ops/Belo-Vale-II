import type { AnchorHTMLAttributes, MouseEvent } from 'react';

/** Link normal com navegação interna: preserva o app e permite abrir em outra aba. */
export function AppLink({ href, children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>): JSX.Element {
  function follow(event: MouseEvent<HTMLAnchorElement>): void {
    props.onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || props.target || !href?.startsWith('/')) return;
    event.preventDefault();
    window.history.pushState({ inApp: true }, '', href);
    window.dispatchEvent(new PopStateEvent('popstate'));
    window.scrollTo(0, 0);
  }
  return <a {...props} href={href} onClick={follow}>{children}</a>;
}
