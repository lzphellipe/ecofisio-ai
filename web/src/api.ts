import type { ItemHistorico, Resposta } from "./types";

const BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8080").replace(/\/$/, "");
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
  perguntar: (pergunta: string) =>
    pedir<Resposta>("/perguntar", { method: "POST", body: JSON.stringify({ pergunta }) }),
  historico: () => pedir<ItemHistorico[]>("/historico"),
  item: (id: string) => pedir<Resposta>(`/historico/${encodeURIComponent(id)}`),
};
