import { useState } from "react";

/**
 * Como pôr o Belo Vale na tela inicial do celular.
 *
 * Instalado, ele abre em tela cheia, guarda o app para abrir sem sinal e
 * fica a um toque. O Android oferece "Instalar app" sozinho; o iPhone não
 * avisa nada — o caminho fica escondido no botão Compartilhar do Safari, e
 * quem não é da área não descobre.
 */

type Aparelho = "iphone" | "android" | "outro";

function aparelho(): Aparelho {
  const agente = navigator.userAgent;
  // iPad com iPadOS se apresenta como Mac; o toque denuncia.
  if (/iPhone|iPad|iPod/.test(agente) || (/Macintosh/.test(agente) && navigator.maxTouchPoints > 1)) {
    return "iphone";
  }
  if (/Android/.test(agente)) return "android";
  return "outro";
}

function instalado(): boolean {
  const iosStandalone = (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return iosStandalone || window.matchMedia?.("(display-mode: standalone)").matches === true;
}

export function InstallHint(): JSX.Element | null {
  const [qual] = useState(aparelho);
  if (instalado() || qual === "outro") return null;

  return (
    <section className="install-hint" aria-labelledby="instalar-titulo">
      <h3 id="instalar-titulo">Usar como aplicativo</h3>
      <p className="hint">
        Na tela inicial, o Belo Vale abre em tela cheia e funciona mesmo quando o sinal cai no
        curral.
      </p>
      {qual === "iphone" ? (
        <ol>
          <li>
            Abra este endereço no <strong>Safari</strong>.
          </li>
          <li>
            Toque em <strong>Compartilhar</strong> (o quadrado com a seta para cima, embaixo da
            tela).
          </li>
          <li>
            Role e toque em <strong>Adicionar à Tela de Início</strong>, depois em{" "}
            <strong>Adicionar</strong>.
          </li>
          <li>Abra pelo ícone da vaca e entre com seu e-mail e senha.</li>
        </ol>
      ) : (
        <ol>
          <li>
            No <strong>Chrome</strong>, toque nos três pontinhos (canto de cima).
          </li>
          <li>
            Toque em <strong>Instalar app</strong> (ou Adicionar à tela inicial).
          </li>
          <li>Abra pelo ícone da vaca e entre com seu e-mail e senha.</li>
        </ol>
      )}
    </section>
  );
}
