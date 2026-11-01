import type { Resposta } from "./types";

const FORCA: Record<string, string> = {
  consenso: "consenso",
  resultado_isolado: "resultado isolado",
  controverso: "controverso",
  especulacao: "especulação",
};

// Monta um Markdown da resposta — resumo, evidências com DOI, bloqueadas e lacunas —
// pronto para anexar num texto. Tudo no cliente; não precisa do backend.
export function respostaParaMarkdown(r: Resposta): string {
  const l: string[] = [];
  l.push(`# ${r.pergunta}`, "");
  if (r.resumo) l.push(r.resumo, "");

  if (r.entregues.length) {
    l.push("## Evidências", "");
    for (const e of r.entregues) {
      l.push(`- **${e.texto}** _(${FORCA[e.forca] ?? e.forca}; ${e.status})_`);
      for (const c of e.citacoes) {
        const secao = c.secao ? ` — ${c.secao}` : "";
        l.push(`  - https://doi.org/${c.doi}${secao}`);
      }
    }
    l.push("");
  }

  if (r.bloqueadas.length) {
    l.push("## Bloqueadas (não usar sem conferir)", "");
    for (const b of r.bloqueadas) {
      l.push(`- ~~${b.texto}~~ — ${b.motivos.join("; ")}`);
    }
    l.push("");
  }

  if (r.lacunas.length) {
    l.push("## Lacunas", "");
    for (const g of r.lacunas) l.push(`- ${g}`);
    l.push("");
  }

  l.push("---", `Modelo: ${r.modelo} · gerado por ecofísio`);
  return l.join("\n");
}

export function baixarMarkdown(r: Resposta): void {
  const nome =
    r.pergunta
      .toLowerCase()
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 50) || "resposta";
  const blob = new Blob([respostaParaMarkdown(r)], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${nome}.md`;
  a.click();
  URL.revokeObjectURL(url);
}
