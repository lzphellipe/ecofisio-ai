import type {
  Artefato,
  EspecialistaInfo,
  ItemHistorico,
  ModeloInfo,
  Passagem,
  Projeto,
  ProjetoDetalhe,
  Resposta,
} from "./types";

// Sem VITE_API_URL, chama a mesma origem (quando o backend serve o front).
// No dev (Vite em :5173), defina VITE_API_URL=http://localhost:8080 no .env.
const BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");
const AUTH_KEY = "ecofisio.auth";

// Credencial HTTP Basic guardada localmente (conveniência por navegador; a API é que valida).
export function salvarCredencial(usuario: string, senha: string): void {
  try {
    localStorage.setItem(AUTH_KEY, btoa(`${usuario}:${senha}`));
  } catch {
    /* navegador sem storage: segue sem lembrar */
  }
}

export function limparCredencial(): void {
  try {
    localStorage.removeItem(AUTH_KEY);
  } catch {
    /* ignore */
  }
}

function credencial(): string | null {
  try {
    return localStorage.getItem(AUTH_KEY);
  } catch {
    return null;
  }
}

export function temCredencial(): boolean {
  return credencial() !== null;
}

class RespostaDeErro extends Error {
  constructor(
    public status: number,
    mensagem: string,
  ) {
    super(mensagem);
  }
}
export { RespostaDeErro };

async function pedir<T>(caminho: string, init?: RequestInit): Promise<T> {
  const cred = credencial();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (cred) headers.Authorization = `Basic ${cred}`;
  let resp: Response;
  try {
    resp = await fetch(`${BASE}${caminho}`, { ...init, headers: { ...headers, ...init?.headers } });
  } catch {
    throw new RespostaDeErro(0, "Não consegui falar com a API. O servidor está no ar?");
  }
  if (!resp.ok) {
    let detalhe = `erro ${resp.status}`;
    try {
      const corpo = await resp.json();
      if (corpo?.detail) detalhe = String(corpo.detail);
    } catch {
      /* resposta sem JSON */
    }
    throw new RespostaDeErro(resp.status, detalhe);
  }
  return (await resp.json()) as T;
}

export const api = {
  saude: () => pedir<{ status: string; modelo: string; trechos: number }>("/saude"),
  modelos: () => pedir<{ padrao: string; modelos: ModeloInfo[] }>("/modelos"),
  especialistas: () => pedir<EspecialistaInfo[]>("/especialistas"),
  perguntar: (pergunta: string, modelo?: string, especialista?: string) =>
    pedir<Resposta>("/perguntar", {
      method: "POST",
      body: JSON.stringify({ pergunta, modelo, especialista }),
    }),
  historico: () => pedir<ItemHistorico[]>("/historico"),
  item: (id: string) => pedir<Resposta>(`/historico/${encodeURIComponent(id)}`),
  buscar: (q: string, soPrimarios: boolean) => {
    const p = new URLSearchParams({ q, k: "10" });
    if (soPrimarios) p.set("so_primarios", "true");
    return pedir<{ consulta: string; resultados: Passagem[] }>(`/buscar?${p.toString()}`);
  },
  projetos: () => pedir<Projeto[]>("/projetos"),
  criarProjeto: (nome: string) =>
    pedir<Projeto>("/projetos", { method: "POST", body: JSON.stringify({ nome }) }),
  projeto: (id: string) => pedir<ProjetoDetalhe>(`/projetos/${encodeURIComponent(id)}`),
  excluirProjeto: (id: string) =>
    pedir<{ ok: boolean }>(`/projetos/${encodeURIComponent(id)}`, { method: "DELETE" }),
  addAoProjeto: (id: string, perguntaId: string) =>
    pedir<{ id: string; nome: string; n: number }>(
      `/projetos/${encodeURIComponent(id)}/perguntas`,
      { method: "POST", body: JSON.stringify({ pergunta_id: perguntaId }) },
    ),
  artefatos: () => pedir<Artefato[]>("/artefatos"),
  salvarArtefato: (perguntaId: string, nome: string) =>
    pedir<Artefato>("/artefatos", {
      method: "POST",
      body: JSON.stringify({ pergunta_id: perguntaId, nome }),
    }),
  excluirArtefato: (id: string) =>
    pedir<{ ok: boolean }>(`/artefatos/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
