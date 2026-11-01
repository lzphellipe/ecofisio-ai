import { useCallback, useEffect, useRef, useState } from "react";
import Finding from "./Finding";
import { api, limparCredencial, RespostaDeErro, salvarCredencial, temCredencial } from "./api";
import type { ItemHistorico, Turno } from "./types";

type Sessao = "verificando" | "logado" | "deslogado";

export default function App() {
  const [sessao, setSessao] = useState<Sessao>("verificando");
  const [turnos, setTurnos] = useState<Turno[]>([]);
  const [historico, setHistorico] = useState<ItemHistorico[]>([]);
  const [ocupado, setOcupado] = useState(false);
  const fim = useRef<HTMLDivElement>(null);

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
      /* histórico é secundário; silencia */
    }
  }, []);

  useEffect(() => {
    checarSessao();
  }, [checarSessao]);

  useEffect(() => {
    if (sessao === "logado") carregarHistorico();
  }, [sessao, carregarHistorico]);

  useEffect(() => {
    fim.current?.scrollIntoView({ behavior: "smooth" });
  }, [turnos, ocupado]);

  async function perguntar(pergunta: string) {
    setTurnos((t) => [...t, { pergunta }]);
    setOcupado(true);
    try {
      const resposta = await api.perguntar(pergunta);
      setTurnos((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, resposta } : x)));
      carregarHistorico();
    } catch (e) {
      const erro =
        e instanceof RespostaDeErro && e.status === 401
          ? "Sessão expirada. Entre de novo."
          : e instanceof Error
            ? e.message
            : "erro inesperado";
      setTurnos((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, erro } : x)));
      if (e instanceof RespostaDeErro && e.status === 401) setSessao("deslogado");
    } finally {
      setOcupado(false);
    }
  }

  async function abrirHistorico(id: string) {
    try {
      const resposta = await api.item(id);
      setTurnos((t) => [...t, { pergunta: resposta.pergunta, resposta }]);
    } catch {
      /* ignore */
    }
  }

  if (sessao === "verificando") {
    return <div className="boot">Carregando…</div>;
  }
  if (sessao === "deslogado") {
    return <Login aoEntrar={checarSessao} />;
  }

  return (
    <div className="app">
      <aside className="rail">
        <div className="marca">
          <Marca />
          <div>
            <div className="marca-nome">ecofísio</div>
            <div className="marca-sub">pesquisa em biologia</div>
          </div>
        </div>

        <button
          className="novo"
          onClick={() => setTurnos([])}
          disabled={turnos.length === 0}
        >
          Nova pergunta
        </button>

        <nav className="hist">
          <div className="hist-titulo">Perguntas anteriores</div>
          {historico.length === 0 && <p className="hist-vazio">Nada por aqui ainda.</p>}
          {historico.map((h) => (
            <button key={h.id} className="hist-item" onClick={() => abrirHistorico(h.id)}>
              <span className="hist-q">{h.pergunta}</span>
              <span className="hist-tag">
                {h.entregues} ev.
                {h.bloqueadas > 0 && <span className="hist-bloq"> · {h.bloqueadas} bloq.</span>}
              </span>
            </button>
          ))}
        </nav>

        <button
          className="sair"
          onClick={() => {
            limparCredencial();
            setSessao("deslogado");
          }}
        >
          {temCredencial() ? "Sair" : ""}
        </button>
      </aside>

      <main className="conversa">
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
        <Composer ocupado={ocupado} aoEnviar={perguntar} />
      </main>
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

// Marca própria: uma folha nervurada dentro de um círculo (não é logo de ninguém).
function Marca() {
  return (
    <svg className="marca-icone" viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="16" r="15" className="marca-anel" />
      <path
        d="M16 7 C 11 11, 10 20, 16 25 C 22 20, 21 11, 16 7 Z"
        className="marca-folha"
      />
      <path d="M16 9 L16 24" className="marca-nervura" />
    </svg>
  );
}
