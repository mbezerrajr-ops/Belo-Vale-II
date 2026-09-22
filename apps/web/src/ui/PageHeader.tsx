import type { ReactNode } from "react";

interface Props {
  title: ReactNode;
  /** Uma frase: o que se faz aqui. O resto fica na própria tela. */
  children?: ReactNode;
  /** A ação da área (cadastrar, atualizar), à direita do título. */
  actions?: ReactNode;
}

/** O mesmo topo em todas as áreas: título, uma linha e a ação da área. */
export function PageHeader({ title, children, actions }: Props): JSX.Element {
  return (
    <header className="page-head">
      <div className="page-head-text">
        <h2>{title}</h2>
        {children && <p className="page-lede">{children}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}
