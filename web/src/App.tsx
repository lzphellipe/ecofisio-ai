import { useCallback, useEffect, useRef, useState } from "react";
import Finding from "./Finding";
import {
  api,
  limparCredencial,
  RespostaDeErro,
  salvarCredencial,
  temCredencial,
} from "./api";
import { baixarMarkdown } from "./exportar";
import type {
  Artefato,
  ItemHistorico,
  ModeloInfo,
  Passagem,
  Projeto,
  ProjetoDetalhe,
  Resposta,
  Secao,
  Turno,
} from "./types";

type Sessao = "verificando" | "logado" | "deslogado";
type Tema = "auto" | "claro" | "escuro";

const TEMA_KEY = "ecofisio.tema";

function lerTema(): Tema {
  try {
    const t = localStorage.getItem(TEMA_KEY);
    if (t === "claro" || t === "escuro") return t;
  } catch {
    /* ignore */
  }
  return "auto";
}

function aplicarTema(t: Tema) {
  const el = document.documentElement;
  if (t === "auto") delete el.dataset.theme;
  else el.dataset.theme = t === "escuro" ? "dark" : "light";
  try {
    localStorage.setItem(TEMA_KEY, t);
  } catch {
    /* ignore */
  }
}

export default function App() {
  const [sessao, setSessao] = useState<Sessao>("verificando");
  const [secao, setSecao] = useState<Secao>("conversa");
  const [turnos, setTurnos] = useState<Turno[]>([]);
  const [historico, setHistorico] = useState<ItemHistorico[]>([]);
  const [projetos, setProjetos] = useState<Projeto[]>([]);
  const [modelos, setModelos] = useState<ModeloInfo[]>([]);
  const [modeloSel, setModeloSel] = useState<string>("");
  const [ocupado, setOcupado] = useState(false);
  const [tema, setTema] = useState<Tema>(lerTema);

  useEffect(() => aplicarTema(tema), [tema]);

  const checarSessao = useCallback(async () => {
    try {
      await api.saude();
      setSessao("logado");
    } catch (e) {
      setSessao(e instanceof RespostaDeErro && e.status === 401 ? "deslogado" : "logado");
    }
  }, []);

  const carregarHistorico = useCallback(async () => {
    try {
      setHistorico(await api.historico());
    } catch {
      /* secundário */
    }
  }, []);

  const carregarProjetos = useCallback(async () => {
    try {
      setProjetos(await api.projetos());
    } catch {
      /* secundário */
    }
  }, []);

  const carregarModelos = useCallback(async () => {
    try {
      const m = await api.modelos();
      setModelos(m.modelos);
      let salvo = "";
      try {
        salvo = localStorage.getItem("ecofisio.modelo") ?? "";
      } catch {
        /* ignore */
      }
      setModeloSel(m.modelos.some((x) => x.id === salvo) ? salvo : m.padrao);
    } catch {
      /* secundário */
    }
  }, []);

  function escolherModelo(id: string) {
    setModeloSel(id);
    try {
      localStorage.setItem("ecofisio.modelo", id);
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    checarSessao();
  }, [checarSessao]);
  useEffect(() => {
    if (sessao === "logado") {
      carregarHistorico();
      carregarProjetos();
      carregarModelos();
    }
  }, [sessao, carregarHistorico, carregarProjetos, carregarModelos]);

  async function perguntar(pergunta: string) {
    setTurnos((t) => [...t, { pergunta }]);
    setOcupado(true);
    try {
      const resposta = await api.perguntar(pergunta, modeloSel || undefined);
      setTurnos((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, resposta } : x)));
      carregarHistorico();
    } catch (e) {
      const semSessao = e instanceof RespostaDeErro && e.status === 401;
      const erro = semSessao
        ? "Sessão expirada. Entre de novo."
        : e instanceof Error
          ? e.message
          : "erro inesperado";
      setTurnos((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, erro } : x)));
      if (semSessao) setSessao("deslogado");
    } finally {
      setOcupado(false);
    }
  }

  async function abrir(resposta: Resposta) {
    setTurnos([{ pergunta: resposta.pergunta, resposta }]);
    setSecao("conversa");
  }
  async function abrirPorId(id: string) {
    try {
      abrir(await api.item(id));
    } catch {
      /* ignore */
    }
  }

  if (sessao === "verificando") return <div className="boot">Carregando…</div>;
  if (sessao === "deslogado") return <Login aoEntrar={checarSessao} />;

  return (
    <div className="app">
      <NavRail
        secao={secao}
        irPara={setSecao}
        novaPergunta={() => {
          setTurnos([]);
          setSecao("conversa");
        }}
      />
      <main className="conteudo">
        {secao === "conversa" && (
          <Conversa
            turnos={turnos}
            ocupado={ocupado}
            aoEnviar={perguntar}
            projetos={projetos}
            aoMudarProjetos={carregarProjetos}
            modelos={modelos}
            modeloSel={modeloSel}
            aoEscolherModelo={escolherModelo}
          />
        )}
        {secao === "procurar" && <Procurar />}
        {secao === "historico" && <Historico itens={historico} aoAbrir={abrir} />}
        {secao === "projetos" && (
          <Projetos
            projetos={projetos}
            aoMudar={carregarProjetos}
            aoAbrirPergunta={abrirPorId}
          />
        )}
        {secao === "artefatos" && <Artefatos aoAbrirPergunta={abrirPorId} />}
        {secao === "config" && (
          <Config
            tema={tema}
            setTema={setTema}
            aoSair={() => {
              limparCredencial();
              setSessao("deslogado");
            }}
          />
        )}
      </main>
    </div>
  );
}

/* ---------- navegação ---------- */
function NavRail({
  secao,
  irPara,
  novaPergunta,
}: {
  secao: Secao;
  irPara: (s: Secao) => void;
  novaPergunta: () => void;
}) {
  return (
    <aside className="rail">
      <div className="marca">
        <Marca />
        <div>
          <div className="marca-nome">ecofísio</div>
          <div className="marca-sub">pesquisa em biologia</div>
        </div>
      </div>
      <nav className="nav">
        <button className="nav-item nav-criar" onClick={novaPergunta}>
          <Icone nome="mais" />
          Nova pergunta
        </button>
        <NavItem atual={secao} alvo="procurar" ir={irPara} icone="lupa" rotulo="Procurar" />
        <NavItem atual={secao} alvo="projetos" ir={irPara} icone="pasta" rotulo="Projetos" />
        <NavItem atual={secao} alvo="artefatos" ir={irPara} icone="estrela" rotulo="Artefatos" />
        <NavItem atual={secao} alvo="historico" ir={irPara} icone="relogio" rotulo="Histórico" />
        <NavItem
          atual={secao}
          alvo="config"
          ir={irPara}
          icone="ajustes"
          rotulo="Personalização"
        />
      </nav>
    </aside>
  );
}

function NavItem({
  atual,
  alvo,
  ir,
  icone,
  rotulo,
}: {
  atual: Secao;
  alvo: Secao;
  ir: (s: Secao) => void;
  icone: IconeNome;
  rotulo: string;
}) {
  return (
    <button
      className={`nav-item${atual === alvo ? " nav-ativo" : ""}`}
      onClick={() => ir(alvo)}
      aria-current={atual === alvo}
    >
      <Icone nome={icone} />
      {rotulo}
    </button>
  );
}

/* ---------- conversa ---------- */
function Conversa({
  turnos,
  ocupado,
  aoEnviar,
  projetos,
  aoMudarProjetos,
  modelos,
  modeloSel,
  aoEscolherModelo,
}: {
  turnos: Turno[];
  ocupado: boolean;
  aoEnviar: (p: string) => void;
  projetos: Projeto[];
  aoMudarProjetos: () => void;
  modelos: ModeloInfo[];
  modeloSel: string;
  aoEscolherModelo: (id: string) => void;
}) {
  const fim = useRef<HTMLDivElement>(null);
  useEffect(() => {
    fim.current?.scrollIntoView({ behavior: "smooth" });
  }, [turnos, ocupado]);
  return (
    <div className="conversa">
      <div className="coluna">
        {turnos.length === 0 && <Vazio />}
        {turnos.map((t, i) => (
          <div key={i} className="turno">
            <div className="pergunta-bolha">{t.pergunta}</div>
            {t.resposta && <Finding resposta={t.resposta} />}
            {t.resposta?.id && (
              <AcoesResposta
                resposta={t.resposta}
                projetos={projetos}
                aoMudarProjetos={aoMudarProjetos}
              />
            )}
            {t.erro && <div className="turno-erro">{t.erro}</div>}
            {!t.resposta && !t.erro && i === turnos.length - 1 && ocupado && <Pensando />}
          </div>
        ))}
        <div ref={fim} />
      </div>
      <Composer
        ocupado={ocupado}
        aoEnviar={aoEnviar}
        modelos={modelos}
        modeloSel={modeloSel}
        aoEscolherModelo={aoEscolherModelo}
      />
    </div>
  );
}

function AcoesResposta({
  resposta,
  projetos,
  aoMudarProjetos,
}: {
  resposta: Resposta;
  projetos: Projeto[];
  aoMudarProjetos: () => void;
}) {
  const [aviso, setAviso] = useState("");
  const id = resposta.id!;

  async function salvar() {
    try {
      await api.salvarArtefato(id, resposta.pergunta);
      setAviso("Salvo nos artefatos.");
    } catch {
      setAviso("Não consegui salvar.");
    }
  }
  async function adicionar(pid: string) {
    if (!pid) return;
    try {
      await api.addAoProjeto(pid, id);
      aoMudarProjetos();
      setAviso(`Adicionada ao projeto “${projetos.find((p) => p.id === pid)?.nome ?? ""}”.`);
    } catch {
      setAviso("Não consegui adicionar ao projeto.");
    }
  }

  return (
    <div className="acoes">
      <button className="acao" onClick={salvar}>
        Salvar como artefato
      </button>
      <button className="acao" onClick={() => baixarMarkdown(resposta)}>
        Exportar .md
      </button>
      {projetos.length > 0 ? (
        <select
          className="acao acao-sel"
          value=""
          onChange={(e) => adicionar(e.target.value)}
          aria-label="Adicionar a projeto"
        >
          <option value="">Adicionar a projeto…</option>
          {projetos.map((p) => (
            <option key={p.id} value={p.id}>
              {p.nome}
            </option>
          ))}
        </select>
      ) : (
        <span className="acao-nota">Crie um projeto para agrupar perguntas</span>
      )}
      {aviso && <span className="acao-aviso">{aviso}</span>}
    </div>
  );
}

function Vazio() {
  return (
    <div className="vazio">
      <h1 className="vazio-titulo">Pergunte e veja a evidência.</h1>
      <p className="vazio-texto">
        Cada afirmação vem com a citação que a sustenta e a força da evidência. O que não se
        sustenta aparece bloqueado — não escondido.
      </p>
    </div>
  );
}

function Pensando() {
  return (
    <div className="pensando" role="status">
      <span className="ponto" />
      <span className="ponto" />
      <span className="ponto" />
      <span className="pensando-txt">buscando na literatura e auditando…</span>
    </div>
  );
}

function Composer({
  ocupado,
  aoEnviar,
  modelos,
  modeloSel,
  aoEscolherModelo,
}: {
  ocupado: boolean;
  aoEnviar: (p: string) => void;
  modelos: ModeloInfo[];
  modeloSel: string;
  aoEscolherModelo: (id: string) => void;
}) {
  const [texto, setTexto] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);
  function enviar() {
    const p = texto.trim();
    if (!p || ocupado) return;
    aoEnviar(p);
    setTexto("");
    if (area.current) area.current.style.height = "auto";
  }
  return (
    <div className="composer-wrap">
      {modelos.length > 1 && (
        <div className="modelo-barra">
          <span className="modelo-rotulo">Modelo</span>
          <select
            className="modelo-sel"
            value={modeloSel}
            onChange={(e) => aoEscolherModelo(e.target.value)}
          >
            {modelos.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="composer">
        <textarea
          ref={area}
          className="composer-area"
          value={texto}
          placeholder="Qual é a sua pergunta de pesquisa?"
          rows={1}
          onChange={(e) => {
            setTexto(e.target.value);
            e.target.style.height = "auto";
            e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`;
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              enviar();
            }
          }}
        />
        <button className="enviar" onClick={enviar} disabled={ocupado || texto.trim() === ""}>
          {ocupado ? "Pesquisando" : "Perguntar"}
        </button>
      </div>
    </div>
  );
}

/* ---------- procurar (corpus) ---------- */
function Procurar() {
  const [q, setQ] = useState("");
  const [soPrimarios, setSoPrimarios] = useState(false);
  const [itens, setItens] = useState<Passagem[] | null>(null);
  const [buscando, setBuscando] = useState(false);
  const [erro, setErro] = useState("");

  async function buscar(e: React.FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    setBuscando(true);
    setErro("");
    try {
      const r = await api.buscar(q.trim(), soPrimarios);
      setItens(r.resultados);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "erro inesperado");
    } finally {
      setBuscando(false);
    }
  }

  return (
    <div className="pagina">
      <div className="pagina-coluna">
        <h2 className="pagina-titulo">Procurar no corpus</h2>
        <p className="pagina-sub">
          Busca lexical direta nos artigos indexados (em inglês rende mais). Sem o modelo — são os
          trechos crus, para você ler e citar.
        </p>
        <form className="busca-form" onSubmit={buscar}>
          <input
            className="busca-input"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="stomatal conductance drought recovery"
            autoFocus
          />
          <button className="enviar" disabled={buscando || !q.trim()}>
            {buscando ? "Buscando" : "Buscar"}
          </button>
        </form>
        <label className="check">
          <input
            type="checkbox"
            checked={soPrimarios}
            onChange={(e) => setSoPrimarios(e.target.checked)}
          />
          Só pesquisa primária (exclui revisões e editoriais)
        </label>

        {erro && <div className="turno-erro">{erro}</div>}
        {itens && itens.length === 0 && (
          <p className="pagina-sub">Nada encontrado. Tente termos em inglês ou mais gerais.</p>
        )}
        <ul className="resultados">
          {itens?.map((p, i) => (
            <li key={i} className="resultado">
              <div className="resultado-cab">
                <span className="resultado-titulo">{p.title || "(sem título)"}</span>
                <span className="meta">{p.year ?? "s/ ano"}</span>
              </div>
              <div className="cit-linha">
                <a className="doi" href={`https://doi.org/${p.doi}`} target="_blank" rel="noreferrer">
                  {p.doi}
                </a>
                <span className="secao">{p.section}</span>
                <span className={`tipo${p.primary_evidence ? "" : " tipo-secundario"}`}>
                  {p.article_type || "tipo desconhecido"}
                </span>
              </div>
              <p className="resultado-texto">{p.text}</p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/* ---------- histórico ---------- */
function Historico({
  itens,
  aoAbrir,
}: {
  itens: ItemHistorico[];
  aoAbrir: (r: Resposta) => void;
}) {
  const [filtro, setFiltro] = useState("");
  const vistos = itens.filter((h) =>
    (h.pergunta ?? "").toLowerCase().includes(filtro.toLowerCase()),
  );
  async function abrir(id: string) {
    try {
      aoAbrir(await api.item(id));
    } catch {
      /* ignore */
    }
  }
  return (
    <div className="pagina">
      <div className="pagina-coluna">
        <h2 className="pagina-titulo">Histórico</h2>
        <p className="pagina-sub">Perguntas anteriores desta e de outras sessões.</p>
        <input
          className="busca-input filtro"
          value={filtro}
          onChange={(e) => setFiltro(e.target.value)}
          placeholder="Filtrar por texto da pergunta"
        />
        {vistos.length === 0 && <p className="pagina-sub">Nada por aqui ainda.</p>}
        <ul className="lista-hist">
          {vistos.map((h) => (
            <li key={h.id}>
              <button className="hist-linha" onClick={() => abrir(h.id)}>
                <span className="hist-linha-q">{h.pergunta}</span>
                {h.resumo && <span className="hist-linha-r">{h.resumo}</span>}
                <span className="hist-linha-tags">
                  <span className="tag-ev">{h.entregues} evidências</span>
                  {h.bloqueadas > 0 && <span className="tag-bloq">{h.bloqueadas} bloqueadas</span>}
                  <span className="meta">{(h.criado_em ?? "").slice(0, 10)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/* ---------- projetos ---------- */
function Projetos({
  projetos,
  aoMudar,
  aoAbrirPergunta,
}: {
  projetos: Projeto[];
  aoMudar: () => void;
  aoAbrirPergunta: (id: string) => void;
}) {
  const [nome, setNome] = useState("");
  const [sel, setSel] = useState<ProjetoDetalhe | null>(null);

  async function criar(e: React.FormEvent) {
    e.preventDefault();
    if (!nome.trim()) return;
    await api.criarProjeto(nome.trim());
    setNome("");
    aoMudar();
  }
  async function abrir(id: string) {
    try {
      setSel(await api.projeto(id));
    } catch {
      /* ignore */
    }
  }
  async function excluir(id: string) {
    await api.excluirProjeto(id);
    if (sel?.id === id) setSel(null);
    aoMudar();
  }

  return (
    <div className="pagina">
      <div className="pagina-coluna">
        <h2 className="pagina-titulo">Projetos</h2>
        <p className="pagina-sub">
          Agrupe perguntas por tema. Nas respostas, use “Adicionar a projeto” para incluí-las aqui.
        </p>
        <form className="busca-form" onSubmit={criar}>
          <input
            className="busca-input"
            value={nome}
            onChange={(e) => setNome(e.target.value)}
            placeholder="Nome do projeto (ex.: Tese — capítulo 2)"
          />
          <button className="enviar" disabled={!nome.trim()}>
            Criar
          </button>
        </form>

        {projetos.length === 0 && <p className="pagina-sub">Nenhum projeto ainda.</p>}
        <ul className="lista-proj">
          {projetos.map((p) => (
            <li key={p.id} className={`proj${sel?.id === p.id ? " proj-aberto" : ""}`}>
              <button className="proj-cab" onClick={() => abrir(p.id)}>
                <span className="proj-nome">{p.nome}</span>
                <span className="meta">
                  {p.n} {p.n === 1 ? "pergunta" : "perguntas"}
                </span>
              </button>
              <button className="proj-excluir" onClick={() => excluir(p.id)} title="Excluir">
                excluir
              </button>
            </li>
          ))}
        </ul>

        {sel && (
          <section className="proj-detalhe">
            <h3 className="bloco-titulo">{sel.nome}</h3>
            {sel.perguntas.length === 0 && (
              <p className="pagina-sub">Sem perguntas ainda neste projeto.</p>
            )}
            <ul className="lista-hist">
              {sel.perguntas.map((h) => (
                <li key={h.id}>
                  <button className="hist-linha" onClick={() => aoAbrirPergunta(h.id)}>
                    <span className="hist-linha-q">{h.pergunta}</span>
                    {h.resumo && <span className="hist-linha-r">{h.resumo}</span>}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}

/* ---------- artefatos ---------- */
function Artefatos({ aoAbrirPergunta }: { aoAbrirPergunta: (id: string) => void }) {
  const [itens, setItens] = useState<Artefato[] | null>(null);
  useEffect(() => {
    api.artefatos().then(setItens).catch(() => setItens([]));
  }, []);

  async function excluir(id: string) {
    await api.excluirArtefato(id);
    setItens((i) => i?.filter((x) => x.id !== id) ?? null);
  }
  async function exportar(perguntaId: string) {
    try {
      baixarMarkdown(await api.item(perguntaId));
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="pagina">
      <div className="pagina-coluna">
        <h2 className="pagina-titulo">Artefatos</h2>
        <p className="pagina-sub">
          Respostas que você salvou. Abra para rever, ou exporte em Markdown para anexar num texto.
        </p>
        {itens && itens.length === 0 && (
          <p className="pagina-sub">Nada salvo ainda. Numa resposta, use “Salvar como artefato”.</p>
        )}
        <ul className="lista-hist">
          {itens?.map((a) => (
            <li key={a.id}>
              <div className="artefato">
                <div className="artefato-info">
                  <span className="hist-linha-q">{a.nome}</span>
                  {a.pergunta && a.pergunta !== a.nome && (
                    <span className="hist-linha-r">{a.pergunta}</span>
                  )}
                  {a.existe === false && (
                    <span className="artefato-sumiu">rastro removido — indisponível</span>
                  )}
                </div>
                <div className="artefato-acoes">
                  {a.existe !== false && (
                    <>
                      <button className="acao" onClick={() => aoAbrirPergunta(a.pergunta_id)}>
                        Abrir
                      </button>
                      <button className="acao" onClick={() => exportar(a.pergunta_id)}>
                        Exportar .md
                      </button>
                    </>
                  )}
                  <button className="acao acao-apagar" onClick={() => excluir(a.id)}>
                    Excluir
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/* ---------- personalização ---------- */
function Config({
  tema,
  setTema,
  aoSair,
}: {
  tema: Tema;
  setTema: (t: Tema) => void;
  aoSair: () => void;
}) {
  const [status, setStatus] = useState<{ modelo: string; trechos: number } | null>(null);
  useEffect(() => {
    api.saude().then(setStatus).catch(() => setStatus(null));
  }, []);
  const temas: { v: Tema; r: string }[] = [
    { v: "auto", r: "Automático (segue o sistema)" },
    { v: "claro", r: "Claro" },
    { v: "escuro", r: "Escuro" },
  ];
  return (
    <div className="pagina">
      <div className="pagina-coluna">
        <h2 className="pagina-titulo">Personalização</h2>

        <section className="bloco">
          <h3 className="bloco-titulo">Tema</h3>
          <div className="radios">
            {temas.map((t) => (
              <label key={t.v} className="radio">
                <input
                  type="radio"
                  name="tema"
                  checked={tema === t.v}
                  onChange={() => setTema(t.v)}
                />
                {t.r}
              </label>
            ))}
          </div>
        </section>

        <section className="bloco">
          <h3 className="bloco-titulo">Servidor</h3>
          {status ? (
            <dl className="status">
              <dt>Modelo</dt>
              <dd className="mono">{status.modelo}</dd>
              <dt>Trechos no índice</dt>
              <dd className="mono">{status.trechos.toLocaleString("pt-BR")}</dd>
            </dl>
          ) : (
            <p className="pagina-sub">Sem conexão com a API.</p>
          )}
        </section>

        <section className="bloco">
          <h3 className="bloco-titulo">Conta</h3>
          <button className="sair-btn" onClick={aoSair}>
            {temCredencial() ? "Sair" : "Esquecer esta sessão"}
          </button>
        </section>
      </div>
    </div>
  );
}

/* ---------- login ---------- */
function Login({ aoEntrar }: { aoEntrar: () => void }) {
  const [usuario, setUsuario] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  const [tentando, setTentando] = useState(false);
  async function entrar(e: React.FormEvent) {
    e.preventDefault();
    setTentando(true);
    setErro("");
    salvarCredencial(usuario, senha);
    try {
      await api.saude();
      aoEntrar();
    } catch {
      limparCredencial();
      setErro("Usuário ou senha incorretos.");
    } finally {
      setTentando(false);
    }
  }
  return (
    <div className="login">
      <form className="login-cartao" onSubmit={entrar}>
        <div className="marca login-marca">
          <Marca />
          <div className="marca-nome">ecofísio</div>
        </div>
        <label>
          Usuário
          <input value={usuario} onChange={(e) => setUsuario(e.target.value)} autoFocus />
        </label>
        <label>
          Senha
          <input type="password" value={senha} onChange={(e) => setSenha(e.target.value)} />
        </label>
        {erro && <p className="login-erro">{erro}</p>}
        <button type="submit" disabled={tentando}>
          {tentando ? "Entrando" : "Entrar"}
        </button>
      </form>
    </div>
  );
}

/* ---------- marca e ícones ---------- */
function Marca() {
  return (
    <svg className="marca-icone" viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="16" r="15" className="marca-anel" />
      <path d="M16 7 C 11 11, 10 20, 16 25 C 22 20, 21 11, 16 7 Z" className="marca-folha" />
      <path d="M16 9 L16 24" className="marca-nervura" />
    </svg>
  );
}

type IconeNome = "mais" | "lupa" | "relogio" | "ajustes" | "pasta" | "estrela";

function Icone({ nome }: { nome: IconeNome }) {
  const p: Record<IconeNome, JSX.Element> = {
    mais: <path d="M10 4v12M4 10h12" />,
    lupa: (
      <>
        <circle cx="9" cy="9" r="5.5" />
        <path d="M13.5 13.5 L17 17" />
      </>
    ),
    relogio: (
      <>
        <circle cx="10" cy="10" r="7" />
        <path d="M10 6v4l3 2" />
      </>
    ),
    ajustes: (
      <>
        <path d="M4 6h12M4 10h12M4 14h12" />
        <circle cx="8" cy="6" r="1.6" />
        <circle cx="13" cy="10" r="1.6" />
        <circle cx="7" cy="14" r="1.6" />
      </>
    ),
    pasta: <path d="M3 6.5 a1 1 0 0 1 1-1 h3 l1.5 2 h6 a1 1 0 0 1 1 1 v5 a1 1 0 0 1-1 1 H4 a1 1 0 0 1-1-1 Z" />,
    estrela: <path d="M6 4 h8 a1 1 0 0 1 1 1 v11 l-5-3 l-5 3 V5 a1 1 0 0 1 1-1 Z" />,
  };
  return (
    <svg className="icone" viewBox="0 0 20 20" aria-hidden="true">
      {p[nome]}
    </svg>
  );
}
