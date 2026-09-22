import { Component, type ReactNode } from "react";

interface State {
  failed: boolean;
}

/**
 * Uma tela que não abriu não derruba o app.
 *
 * As telas são baixadas quando abertas. Se o sinal cair bem nessa hora (na
 * primeira visita, antes de o app ficar guardado no celular), a parte da tela
 * não chega — e sem isto o React apagava o app inteiro, deixando a tela em
 * branco no meio do curral. Aqui a falha fica só na área, com o que fazer.
 */
export class AreaBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="warning area-failed" role="alert">
        <p>
          Não foi possível abrir esta tela — provavelmente o sinal caiu enquanto ela carregava. O
          que você já lançou continua guardado.
        </p>
        {/* Recarregar busca a tela de novo (a tentativa que falhou fica
            memorizada pelo React; só recarregar pede outra). */}
        <button type="button" onClick={() => window.location.reload()}>
          Tentar de novo
        </button>
      </div>
    );
  }
}
