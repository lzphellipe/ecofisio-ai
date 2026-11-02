// Espelha o que a API devolve (ResearchAnswer.to_dict no backend).

export type Forca = "consenso" | "resultado_isolado" | "controverso" | "especulacao";
export type Status = "medido" | "inferido";

export interface Citacao {
  doi: string;
  secao: string;
  trecho: string;
}

export interface Entregue {
  texto: string;
  forca: Forca;
  status: Status;
  citacoes: Citacao[];
  avisos: string[];
  verificacao_semantica?: unknown;
}

export interface Bloqueada {
  texto: string;
  motivos: string[];
}

export interface Resposta {
  id?: string;
  pergunta: string;
  modelo: string;
  criado_em: string;
  resumo: string;
  entregues: Entregue[];
  bloqueadas: Bloqueada[];
  lacunas: string[];
  buscas: string[];
  passos: number;
  reparos: number;
  uso_tokens: Record<string, number>;
}

export interface ItemHistorico {
  id: string;
  pergunta: string;
  criado_em: string;
  resumo: string;
  entregues: number;
  bloqueadas: number;
}

// Um turno na conversa: a pergunta e, quando chega, a resposta (ou um erro).
export interface Turno {
  pergunta: string;
  resposta?: Resposta;
  erro?: string;
}

// Resultado da busca direta no corpus (endpoint /buscar).
export interface Passagem {
  doi: string;
  title: string;
  year: number | null;
  section: string;
  license: string;
  article_type: string;
  primary_evidence: boolean;
  text: string;
  score: number;
}

export type Secao =
  | "conversa"
  | "procurar"
  | "historico"
  | "projetos"
  | "artefatos"
  | "config";

export interface Projeto {
  id: string;
  nome: string;
  criado_em: string;
  n: number;
}

export interface ProjetoDetalhe extends Omit<Projeto, "n"> {
  perguntas: ItemHistorico[];
}

export interface ModeloInfo {
  id: string;
  label: string;
  modelo: string;
}

export interface EspecialistaInfo {
  id: string;
  label: string;
}

export interface Artefato {
  id: string;
  pergunta_id: string;
  nome: string;
  criado_em: string;
  pergunta?: string | null;
  existe?: boolean;
}
