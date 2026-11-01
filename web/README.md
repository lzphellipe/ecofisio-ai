# Front web (React + Vite)

Interface de pesquisa do ecofisio-ai: uma pergunta, a resposta e o **painel de evidências** —
cada afirmação com DOI, seção, trecho e força da evidência; o que não se sustenta aparece
bloqueado. Consome a API em [`../src/ecofisio/api`](../src/ecofisio/api) (`docs/api-web.md`).

## Rodar em desenvolvimento

```bash
cd web
npm install
cp .env.example .env     # ajuste VITE_API_URL se a API não estiver em localhost:8080
npm run dev              # http://localhost:5173
```

Suba a API antes (`ecofisio-api`). Se a API estiver na VM do Brev e o front no seu PC, abra o túnel
da porta 8080 além da 8000:

```bash
ssh -N -L 8000:localhost:8000 -L 8080:localhost:8080 <host-ssh-do-brev>
```

Se a API tiver `ECOFISIO_API_USERS`, a tela pede usuário e senha; senão, entra direto.

## Build

```bash
npm run build            # gera dist/
npm run preview          # serve o dist/ localmente para conferir
```

Para publicar junto da API (um endereço só), sirva o conteúdo de `dist/` por trás do mesmo host —
ou configure o `VITE_API_URL` para o endereço público da API e hospede o `dist/` onde preferir.

## Estrutura

- `src/App.tsx` — layout, login, histórico, composer e orquestração.
- `src/Finding.tsx` — a ficha de resposta com o livro-razão de evidências.
- `src/api.ts` — cliente da API (HTTP Basic guardado no navegador).
- `src/styles.css` — o tema (variáveis de cor claro/escuro; a força da evidência tem cor própria).
