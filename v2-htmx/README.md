# 🦁 Leo Tracker v2 (FastAPI + HTMX + Tailwind CSS)

Aplicação web leve e reativa baseada exclusivamente no `@app.py` original, construída com **FastAPI**, **Jinja2**, **Tailwind CSS** e **HTMX** sobre o banco **Neon PostgreSQL**.

## ✨ Módulos Implementados

1. **Bloqueio de Acesso (Autenticação):**
   - Tela de login (`/login`) e encerramento de sessão (`/logout` — botão **🚪 Sair** no topo).
   - Todas as rotas (incluindo os endpoints HTMX `/partials/*`) são protegidas por cookie assinado (`SessionMiddleware`) validado contra `APP_PASSWORD` (ou `PASSWORD`) do `.env`.
2. **Controle de Peso e Medidas Corporais:**
   - Registro rápido de peso em `public.peso`, progresso até a meta e gráfico/histórico com tendência suavizada **EWMA de 10 dias** (*Hacker's Diet*).
   - Aba **📏 Medidas Corporais** com cálculo automático pela fórmula `calc_bf_weltman(waist, weight_kg, height_cm, gender)`, gravação simultânea em `public.body_measurements` e `public.peso`, atualização de `ultima_cintura` em `public.perfil` (`id = 1`) e histórico completo.
3. **Macronutrientes, Alimentação e Histórico:**
   - Registro em `public.consumo` via texto livre (`GROQ_MODEL_TEXT = "openai/gpt-oss-120b"`), foto do prato/rótulo (`GROQ_MODEL_VISION = "qwen/qwen3.8-27b"` com `otimizar_imagem_base64`) e colagem direta de JSON, mantendo `kcal = max(p*4 + c*4 + g*9, kcal)`.
   - Cards de progresso diário e exclusão dinâmica via HTMX (`hx-delete`).
   - Aba **📜 Histórico** com filtro por período (`De` / `Até`), métricas consolidadas (Total Kcal, Média Proteína/dia, Refeições registradas), ranking Top 15 com `padronizar_alimento` e tabela de auditoria.
4. **Exercícios e Sincronização com Intervals.icu:**
   - Reutiliza `conectar_intervals(dias_retroativos=7)` e `sincronizar_treinos_recentes(engine)` com upsert em `public.exercicios` (`ON CONFLICT (id_atividade) DO UPDATE SET ...`), lendo `INTERVALS_API_KEY` e `INTERVALS_ATHLETE_ID` do `.env`.
   - Botão HTMX para sincronizar treinos, formulário de fechamento diário de passos do relógio e formulário de adição manual de atividades.
5. **Configurações e Metas:**
   - Aba **⚙️ Configurações** para visualizar e atualizar em `public.perfil` (`id = 1`): `fator_atividade`, `meta_kcal`, `meta_proteina`, `meta_carbo`, `meta_gordura`, `meta_peso_alvo` e `ritmo_semanal`.

> **Escopo enxuto:** Água/hidratação, café, sono, evacuação/escala de Bristol e pressão arterial foram mantidos inteiramente de fora.

## 🚀 Como Executar Localmente

```bash
cd v2-htmx
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
