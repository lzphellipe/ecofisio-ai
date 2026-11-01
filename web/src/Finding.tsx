import { useState } from "react";
import type { Entregue, Forca, Resposta, Status } from "./types";

const FORCA_LABEL: Record<Forca, string> = {
  consenso: "Consenso",
  resultado_isolado: "Resultado isolado",
  controverso: "Controverso",
  especulacao: "Especulação",
};

const STATUS_LABEL: Record<Status, string> = {
  medido: "Medido",
  inferido: "Inferido",
};

function Citacoes({ item }: { item: Entregue }) {
  const [aberto, setAberto] = useState<number | null>(null);
  return (
    <ul className="citacoes">
      {item.citacoes.map((c, i) => (
        <li key={i}>
          <div className="cit-linha">
            <a
              className="doi"
              href={`https://doi.org/${c.doi}`}
              target="_blank"
              rel="noreferrer"
            >
              {c.doi}
            </a>
            {c.secao && <span className="secao">{c.secao}</span>}
            {c.trecho && (
              <button
                className="ver-trecho"
                onClick={() => setAberto(aberto === i ? null : i)}
                aria-expanded={aberto === i}
              >
                {aberto === i ? "ocultar trecho" : "ver trecho"}
              </button>
            )}
          </div>
          {aberto === i && c.trecho && <blockquote className="trecho">{c.trecho}</blockquote>}
        </li>
      ))}
    </ul>
  );
}

export default function Finding({ resposta }: { resposta: Resposta }) {
  const { resumo, entregues, bloqueadas, lacunas, buscas, modelo, passos } = resposta;
  return (
    <article className="ficha">
      <p className="resumo">{resumo || "(sem resumo)"}</p>

      {entregues.length > 0 && (
        <section className="razao">
          <h3 className="razao-titulo">Evidências</h3>
          {entregues.map((item, i) => (
            <div key={i} className={`afirmacao forca-${item.forca}`}>
              <div className="chips">
                <span className="chip chip-forca">{FORCA_LABEL[item.forca] ?? item.forca}</span>
                <span className="chip chip-status">{STATUS_LABEL[item.status] ?? item.status}</span>
              </div>
              <p className="afirmacao-texto">{item.texto}</p>
              <Citacoes item={item} />
              {item.avisos?.map((a, j) => (
                <p key={j} className="aviso">
                  {a}
                </p>
              ))}
            </div>
          ))}
        </section>
      )}

      {bloqueadas.length > 0 && (
        <section className="bloqueadas">
          <h3 className="razao-titulo">
            Bloqueadas <span className="contagem">{bloqueadas.length}</span>
          </h3>
          <p className="bloqueadas-nota">
            O modelo propôs isto, mas não passou na auditoria. Não use sem conferir na fonte.
          </p>
          {bloqueadas.map((b, i) => (
            <div key={i} className="bloqueada">
              <p className="bloqueada-texto">{b.texto}</p>
              <ul className="motivos">
                {b.motivos.map((m, j) => (
                  <li key={j}>{m}</li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      )}

      {lacunas.length > 0 && (
        <section className="lacunas">
          <h3 className="razao-titulo">Lacunas</h3>
          <ul>
            {lacunas.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </section>
      )}

      <footer className="ficha-rodape">
        {buscas.length > 0 && (
          <div className="buscas">
            {buscas.map((b, i) => (
              <span key={i} className="busca-tag">
                {b}
              </span>
            ))}
          </div>
        )}
        <span className="meta">
          {modelo} · {passos} {passos === 1 ? "passo" : "passos"}
        </span>
      </footer>
    </article>
  );
}
