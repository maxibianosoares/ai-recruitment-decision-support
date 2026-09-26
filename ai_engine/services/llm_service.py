import json
import requests

from .model_config import (
    MODEL_NAME,
    OLLAMA_GENERATE_URL,
    OLLAMA_TIMEOUT_SECONDS,
    OLLAMA_KEEP_ALIVE,
    LLM_PROVIDER,
    call_online_gemma
)


def generate_json(
    prompt,
    default=None,
    num_predict=None
):
    """
    num_predict (Phase 23, controlled experiment ONLY): optional cap on
    the number of tokens Ollama generates for this call. Default is
    None, which means the payload sent to Ollama is BYTE-IDENTICAL to
    before this parameter existed (no "options" key at all) -- so
    every existing caller (analyze_cv, generate_recruitment_assessment,
    and anything that doesn't pass this) keeps its exact current
    behavior with zero change. Only a caller that explicitly passes a
    number gets a capped generation -- used by
    phase23_num_predict_benchmark.py to compare configurations without
    touching production behavior until an experiment result is
    reviewed and approved.
    """

    try:

        if LLM_PROVIDER == "online_gemma":

            raw_response = call_online_gemma(prompt, want_json=True)

        else:

            payload = {
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                # Phase 22 candidate #2 (see model_config.py comment) --
                # keeps gemma3:4b resident in memory between requests
                # instead of Ollama's default 5-minute unload, to avoid
                # a measured cold-reload cost. Does not affect the
                # prompt, the model, or the generated response.
                "keep_alive": OLLAMA_KEEP_ALIVE
            }

            if num_predict is not None:
                # Phase 23 experiment path only -- omitted entirely
                # (not even an empty "options": {}) when num_predict is
                # not passed, so the default request shape is unchanged.
                payload["options"] = {"num_predict": num_predict}

            response = requests.post(
                OLLAMA_GENERATE_URL,
                json=payload,
                timeout=OLLAMA_TIMEOUT_SECONDS
            )

            response.raise_for_status()

            data = response.json()

            raw_response = data.get(
                "response",
                ""
            )

            # Phase 22 candidate #3 (measurement only, not yet an
            # optimization -- see chat reply): log the actual response
            # length AND Ollama's own full timing breakdown, so a real
            # num_predict cap (and a real answer on whether keep_alive
            # is preventing reloads) can be based on evidence instead
            # of guessed. Ollama's /api/generate response already
            # includes all of these fields for free -- nothing here
            # triggers an extra request or changes what is returned or
            # how it is parsed below. All durations are nanoseconds, as
            # returned by Ollama; converted to seconds for readability.
            #   total_duration        -- the whole request, start to end
            #   load_duration         -- time spent loading the model
            #                            into memory (near-zero if the
            #                            model was already warm/resident
            #                            -- this is the direct evidence
            #                            for whether keep_alive avoided
            #                            a reload, not an inference from
            #                            wall-clock variance)
            #   prompt_eval_count/    -- tokens in the prompt, and time
            #   prompt_eval_duration     spent processing them
            #   eval_count/           -- tokens generated, and time
            #   eval_duration            spent generating them
            ns_to_s = lambda ns: (ns / 1e9) if isinstance(ns, (int, float)) else None
            total_d = ns_to_s(data.get("total_duration"))
            load_d = ns_to_s(data.get("load_duration"))
            prompt_eval_d = ns_to_s(data.get("prompt_eval_duration"))
            eval_d = ns_to_s(data.get("eval_duration"))
            print(
                f"LLM response length: {len(raw_response)} chars | "
                f"total_duration={total_d}s "
                f"load_duration={load_d}s "
                f"prompt_eval_count={data.get('prompt_eval_count', 'n/a')} "
                f"prompt_eval_duration={prompt_eval_d}s "
                f"eval_count={data.get('eval_count', 'n/a')} "
                f"eval_duration={eval_d}s"
            )

        if not raw_response:
            return default or {}

        return json.loads(
            raw_response
        )

    except Exception as e:

        print(
            "LLM Error:",
            str(e)
        )

        return default or {}