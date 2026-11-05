import { LogoMark } from "./Brand";
import { useActiveFarm } from "../features/workspace/context";

/**
 * O alto de tudo que o sistema imprime: marca, que documento é, uma
 * etiqueta (o lote, o filtro) e a data, com a linha das colinas embaixo.
 * Só aparece no papel; o estilo mora em `.print-area.ps` (app.css).
 */
export function PrintHeader({
  kind,
  tag,
  date,
}: {
  /** O documento: "Folha de coleta de leite", "Lista de animais". */
  kind: string;
  tag: string | null;
  date: string;
}): JSX.Element {
  const farm = useActiveFarm();
  return (
    <>
      <header className="ps-head">
        <div className="ps-brand">
          <LogoMark size={42} />
          <div>
            <strong>{farm?.name ?? "Belo Vale II"}</strong>
            <span>{kind}</span>
          </div>
        </div>
        <div className="ps-when">
          {tag && <span className="ps-lot">{tag}</span>}
          <span className="ps-date">{date}</span>
        </div>
      </header>
      <svg className="ps-hills" viewBox="0 0 1200 22" preserveAspectRatio="none" aria-hidden="true">
        <path d="M0 16 C 110 4, 220 4, 330 13 S 560 22, 680 11 S 900 1, 1020 10 S 1160 18, 1200 12" />
      </svg>
    </>
  );
}
