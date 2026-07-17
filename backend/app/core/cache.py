import os
import json
import hashlib
from typing import Any

# Dynamic cache file resolution: Use persistent /home/data on Azure Linux, fall back to local root in dev
if os.path.exists("/home") and ("WEBSITE_SITE_NAME" in os.environ or "WEBSITE_INSTANCE_ID" in os.environ):
    PERSISTENT_DIR = "/home/data"
    os.makedirs(PERSISTENT_DIR, exist_ok=True)
    CACHE_FILE = os.path.join(PERSISTENT_DIR, "llm_cache.json")
else:
    CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "llm_cache.json")

class CachedAIMessage:
    """Mock object to simulate LangChain's AIMessage structure."""
    def __init__(self, content: str):
        self.content = content

class CachedStructuredRunnable:
    """Wraps the Runnable returned by with_structured_output to support caching."""
    def __init__(self, base_runnable, cache_llm, schema):
        self.base_runnable = base_runnable
        self.cache_llm = cache_llm
        self.schema = schema

    def invoke(self, input_data: Any) -> Any:
        if isinstance(input_data, str):
            prompt_str = input_data
        elif hasattr(input_data, 'to_string'):
            prompt_str = input_data.to_string()
        else:
            try:
                prompt_str = str(input_data)
            except Exception:
                return self.base_runnable.invoke(input_data)

        prompt_hash = self.cache_llm._get_hash(prompt_str)
        structured_hash = f"struct_{prompt_hash}"

        if structured_hash in self.cache_llm.cache:
            cached_data = self.cache_llm.cache[structured_hash]
            print(f"[LLM Cache Hit] Returning cached structured response for hash: {prompt_hash[:8]}")
            if self.schema and hasattr(self.schema, 'parse_obj'):
                return self.schema.parse_obj(cached_data)
            elif self.schema and hasattr(self.schema, 'model_validate'):
                return self.schema.model_validate(cached_data)
            return cached_data

        print(f"[LLM Cache Miss] Calling real AI API for structured hash: {prompt_hash[:8]}")
        response = self.base_runnable.invoke(input_data)

        if response:
            if hasattr(response, 'dict'):
                serialized = response.dict()
            elif hasattr(response, 'model_dump'):
                serialized = response.model_dump()
            else:
                serialized = response
            self.cache_llm.cache[structured_hash] = serialized
            self.cache_llm._save_cache()

        return response

_cache_memory = None

class CachedLLM:
    """
    Wraps a LangChain Chat Model to intercept `.invoke()` calls.
    Caches the prompt string and its response in a local JSON file to save API costs.
    """
    def __init__(self, base_llm):
        self.base_llm = base_llm
        global _cache_memory
        if _cache_memory is None:
            _cache_memory = self._load_cache()
        self.cache = _cache_memory

    def with_structured_output(self, schema, **kwargs):
        if hasattr(self.base_llm, 'with_structured_output'):
            base_runnable = self.base_llm.with_structured_output(schema, **kwargs)
            return CachedStructuredRunnable(base_runnable, self, schema)
        return self

    def _load_cache(self) -> dict:
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load LLM cache: {e}")
        return {}

    def _save_cache(self):
        try:
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Failed to save LLM cache: {e}")

    def _get_hash(self, text: str) -> str:
        """Create a stable hash of the input prompt."""
        return hashlib.md5(text.encode('utf-8')).hexdigest()

    def invoke(self, input_data: Any) -> Any:
        """
        Intercepts the invoke call. 
        If input_data is a string (which is how our agents use it), we hash it.
        Otherwise, we fall back to the base_llm.
        """
        # Ensure we can stringify the input cleanly for hashing
        if isinstance(input_data, str):
            prompt_str = input_data
        elif hasattr(input_data, 'to_string'):
            prompt_str = input_data.to_string()
        else:
            # If it's a list of messages or something complex, we try to stringify
            try:
                prompt_str = str(input_data)
            except Exception:
                # Fallback to direct call if we can't hash it
                return self.base_llm.invoke(input_data)

        # 1. Check Cache
        prompt_hash = self._get_hash(prompt_str)
        if prompt_hash in self.cache:
            print(f"[LLM Cache Hit] Returning cached response for hash: {prompt_hash[:8]}")
            return CachedAIMessage(content=self.cache[prompt_hash])

        # 2. Cache Miss -> Call real LLM
        print(f"[LLM Cache Miss] Calling real AI API for hash: {prompt_hash[:8]}")
        
        # Diagnostic: Save the prompt that caused the miss so we can inspect it in SSH
        try:
            p_dir = PERSISTENT_DIR if 'PERSISTENT_DIR' in globals() else "/home/data"
            with open(os.path.join(p_dir, "last_miss_prompt.txt"), "w", encoding="utf-8") as diag_f:
                diag_f.write(prompt_str)
        except Exception:
            pass

        response = self.base_llm.invoke(input_data)

        # 3. Save to Cache
        if hasattr(response, 'content'):
            self.cache[prompt_hash] = response.content
            self._save_cache()

        return response
