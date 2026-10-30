#!/bin/bash
# Запуск на поде RunPod: всё считается на сервере, обрыв связи работе не мешает.
#   nohup bash scripts/pod_run.sh eval > eval.log 2>&1 &   — тест на 60 строках
#   nohup bash scripts/pod_run.sh full > full.log 2>&1 &   — дозаполнение и исправления
set -u
cd "$(dirname "$0")/.."
MODEL=${MODEL:-gemma3:27b}
pip install -q openai 2>&1 | tail -1
curl -s 127.0.0.1:11434/api/version >/dev/null || {
  OLLAMA_HOST=127.0.0.1:11434 OLLAMA_CONTEXT_LENGTH=16384 OLLAMA_NUM_PARALLEL=4 nohup ollama serve > /tmp/ollama.log 2>&1 &
  sleep 6
}
ollama list | grep -q "$MODEL" || ollama pull "$MODEL"
export LOCQA_MODEL="ollama/$MODEL" LOCQA_WORKERS=4 LOCQA_BATCH=5 OPENAI_API_KEY= GEMINI_API_KEY=
if [ "${1:-eval}" = "eval" ]; then
  python3 scripts/eval_local.py "ollama/$MODEL" 60 5
else
  LOCQA_FALLBACK_CACHE=gpt-5.4:low python3 scripts/run_llm_part.py
fi
echo "DONE"
