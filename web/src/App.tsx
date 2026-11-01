import { useCallback, useEffect, useRef, useState } from "react";
import Finding from "./Finding";
import {
  api,
  limparCredencial,
  RespostaDeErro,
  salvarCredencial,
  temCredencial,
} from "./api";
import type { ItemHistorico, Passagem, Resposta, Secao, Turno } from "./types";

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

  useEffect(() => {
    checarSessao();
  }, [checarSessao]);
  useEffect(() => {
    if (sessao === "logado") carregarHistorico();
  }, [sessao, carregarHistorico]);

  async function perguntar(pergunta: string) {
    setTurnos((t) => [...t, { pergunta }]);
    setOcupado(true);
    try {
      const resposta = await api.perguntar(pergunta);
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

  async function abrirDoHistorico(resposta: Resposta) {
    setTurnos([{ pergunta: resposta.pergunta, resposta }]);
    setSecao("conversa");
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
          <Conversa turnos={turnos} ocupado={ocupado} aoEnviar={perguntar} />
        )}
        {secao === "procurar" && <Procurar />}
        {secao === "historico" && (
          <Historico itens={historico} aoAbrir={abrirDoHistorico} />
        )}
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
        <NavItem
          atual={secao}
          alvo="historico"
          ir={irPara}
          icone="relogio"
          rotulo="Histórico"
        />
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
}: {
  turnos: Turno[];
  ocupado: boolean;
  aoEnviar: (p: string) => void;
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
            {t.erro && <div className="turno-erro">{t.erro}</div>}
            {!t.resposta && !t.erro && i === turnos.length - 1 && ocupado && <Pensando />}
          </div>
        ))}
        <div ref={fim} />
      </div>
      <Composer ocupado={ocupado} aoEnviar={aoEnviar} />
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
}: {
  ocupado: boolean;
  aoEnviar: (p: string) => void;
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

type IconeNome = "mais" | "lupa" | "relogio" | "ajustes";

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
  };
  return (
    <svg className="icone" viewBox="0 0 20 20" aria-hidden="true">
      {p[nome]}
    </svg>
  );
}
