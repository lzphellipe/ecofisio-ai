# Mini-kernel de inferência (trilho 2)

Inferência de um modelo pequeno (até ~1B parâmetros) em C++/CUDA puro, para aprendizado e pesquisa. Roda em paralelo ao projeto e nunca bloqueia o trilho de produção (`kernels/`).

Cada etapa só avança quando a saída bate com o PyTorch dentro de uma tolerância explícita:

1. Carregar pesos (safetensors) e rodar o forward em C++ na CPU.
2. Portar matmul, RMSNorm, RoPE, atenção e SwiGLU para CUDA, um kernel por vez.
3. Cache KV e geração token a token.
4. Quantização (int8, depois 4 bits) e medição de tokens/s contra PyTorch e llama.cpp.
5. Opcional: carregar o adaptador LoRA do modelo especialista e servi-lo por aqui.

Ainda não iniciado.
