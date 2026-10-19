"""
llm_providers.py
-----------------
Camada de abstração agnóstica de modelo de IA (Seção 11 do Documento de
Contexto): o Sophia não tem motor próprio, o usuário escolhe o provedor
(OpenAI, Anthropic, Google ou Groq) e fornece sua própria chave (BYOK).

Cada provedor implementa `generate(system_prompt, user_prompt, use_web_search, expect_json)`
e retorna um `LLMResponse` com o texto bruto (JSON quando expect_json=True,
validado depois em analysis.py; texto livre quando expect_json=False) e a
lista de `citations` — URLs REAIS que a ferramenta de busca web do próprio
provedor consultou/citou nesta chamada.

IMPORTANTE (mesmo princípio da regra 1 de analysis.py): `citations` é a
única fonte de verdade sobre "quais URLs existem de verdade" nesta análise.
O texto/JSON gerado pelo modelo pode mencionar uma URL que ele inventou —
analysis.py deve validar toda `fonte_url` contra esta lista antes de
confiar nela. Nunca trate uma URL só porque ela "apareceu no JSON" como
verificada.

Chaves de API NUNCA são logadas nem persistidas em disco por este módulo —
isso é responsabilidade da camada de armazenamento (ver app.py /
storage.py), que deve criptografá-las at-rest.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List

# Timeout (segundos) para todas as chamadas de rede aos provedores.
# Evita que uma chamada travada prenda a request Flask indefinidamente.
DEFAULT_TIMEOUT_S = 90.0


class LLMError(RuntimeError):
    """Erro de comunicação com o provedor de IA escolhido pelo usuário."""


@dataclass
class Citation:
    url: str
    title: str = ""


@dataclass
class LLMResponse:
    text: str
    citations: List[Citation] = field(default_factory=list)

    @property
    def citation_urls(self) -> set[str]:
        return {c.url for c in self.citations if c.url}


class BaseLLMProvider(ABC):
    name: str

    def __init__(self, api_key: str, model: str | None = None):
        if not api_key:
            raise LLMError("Chave de API não informada para este provedor.")
        self.api_key = api_key
        self.model = model or self.default_model

    @property
    @abstractmethod
    def default_model(self) -> str: ...

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        use_web_search: bool = True,
        expect_json: bool = True,
    ) -> LLMResponse:
        """Retorna o texto da resposta (esperado: um único objeto JSON quando
        expect_json=True; texto livre quando expect_json=False) junto com as
        citações reais (URLs) usadas pela busca web nesta chamada, se houver."""
        ...


class OpenAIProvider(BaseLLMProvider):
    name = "openai"
    default_model = "gpt-4.1"

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        use_web_search: bool = True,
        expect_json: bool = True,
    ) -> LLMResponse:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise LLMError("Pacote 'openai' não instalado (pip install openai).") from e

        client = OpenAI(api_key=self.api_key, timeout=DEFAULT_TIMEOUT_S)
        tools = [{"type": "web_search_preview"}] if use_web_search else []

        try:
            resp = client.responses.create(
                model=self.model,
                instructions=system_prompt,
                input=user_prompt,
                tools=tools or None,
            )
            citations: List[Citation] = []
            # A Responses API anexa "annotations" do tipo url_citation aos
            # blocos de texto de saída quando a tool de busca web é usada.
            for item in getattr(resp, "output", []) or []:
                for content in getattr(item, "content", []) or []:
                    for ann in getattr(content, "annotations", []) or []:
                        if getattr(ann, "type", None) == "url_citation":
                            citations.append(
                                Citation(
                                    url=getattr(ann, "url", "") or "",
                                    title=getattr(ann, "title", "") or "",
                                )
                            )
            return LLMResponse(text=resp.output_text, citations=citations)
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"Falha ao chamar a OpenAI: {e}") from e


class AnthropicProvider(BaseLLMProvider):
    name = "anthropic"
    default_model = "claude-sonnet-4-6"

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        use_web_search: bool = True,
        expect_json: bool = True,
    ) -> LLMResponse:
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("Pacote 'anthropic' não instalado (pip install anthropic).") from e

        client = anthropic.Anthropic(api_key=self.api_key, timeout=DEFAULT_TIMEOUT_S)
        tools = [{"type": "web_search_20250305", "name": "web_search"}] if use_web_search else []

        try:
            resp = client.messages.create(
                model=self.model,
                max_tokens=4000,
                system=system_prompt,
                tools=tools or None,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text_parts = []
            citations: List[Citation] = []
            for block in resp.content:
                btype = getattr(block, "type", None)
                if btype == "text":
                    text_parts.append(block.text)
                    # Citações inline anexadas ao próprio bloco de texto
                    for cit in getattr(block, "citations", None) or []:
                        url = getattr(cit, "url", None)
                        if url:
                            citations.append(
                                Citation(url=url, title=getattr(cit, "title", "") or "")
                            )
                elif btype == "web_search_tool_result":
                    # Resultados brutos da busca (cada página consultada),
                    # independente de terem sido citados no texto final.
                    content = getattr(block, "content", None) or []
                    for result in content:
                        url = getattr(result, "url", None)
                        if url:
                            citations.append(
                                Citation(url=url, title=getattr(result, "title", "") or "")
                            )
            return LLMResponse(text="\n".join(text_parts), citations=citations)
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"Falha ao chamar a Anthropic: {e}") from e


class GoogleProvider(BaseLLMProvider):
    name = "google"
    default_model = "gemini-3.5-flash"

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        use_web_search: bool = True,
        expect_json: bool = True,
    ) -> LLMResponse:
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise LLMError("Pacote 'google-genai' não instalado (pip install google-genai).") from e

        client = genai.Client(api_key=self.api_key)
        tools = [types.Tool(google_search=types.GoogleSearch())] if use_web_search else []

        try:
            resp = client.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=tools or None,
                    http_options=types.HttpOptions(timeout=int(DEFAULT_TIMEOUT_S * 1000)),
                ),
            )
            citations: List[Citation] = []
            candidates = getattr(resp, "candidates", None) or []
            for cand in candidates:
                grounding = getattr(cand, "grounding_metadata", None)
                if not grounding:
                    continue
                for chunk in getattr(grounding, "grounding_chunks", None) or []:
                    web = getattr(chunk, "web", None)
                    if web and getattr(web, "uri", None):
                        citations.append(
                            Citation(url=web.uri, title=getattr(web, "title", "") or "")
                        )
            return LLMResponse(text=resp.text, citations=citations)
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"Falha ao chamar o Google Gemini: {e}") from e


class GroqProvider(BaseLLMProvider):
    name = "groq"
    default_model = "openai/gpt-oss-120b"

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        use_web_search: bool = True,
        expect_json: bool = True,
    ) -> LLMResponse:
        try:
            from groq import Groq
        except ImportError:
            # Fallback para usar o pacote 'openai' com o endpoint do Groq
            try:
                from openai import OpenAI

                client = OpenAI(
                    base_url="https://api.groq.com/openai/v1",
                    api_key=self.api_key,
                    timeout=DEFAULT_TIMEOUT_S,
                )
            except ImportError as e:
                raise LLMError("Pacote 'groq' ou 'openai' não instalado (pip install groq).") from e
        else:
            client = Groq(api_key=self.api_key, timeout=DEFAULT_TIMEOUT_S)

        try:
            # Nota: Groq não possui busca web nativa no Chat Completions
            # básico, então nunca temos citações reais aqui — qualquer
            # fonte_url que o modelo colocar no JSON será descartada pela
            # validação em analysis.py (nenhuma citação real = nenhuma URL
            # confiável), exatamente como já fazemos para número de
            # processo "não verificado".
            kwargs = dict(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            if expect_json:
                kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**kwargs)
            return LLMResponse(text=resp.choices[0].message.content or "", citations=[])
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"Falha ao chamar o Groq: {e}") from e


PROVIDERS = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "groq": GroqProvider,
}


def get_provider(name: str, api_key: str, model: str | None = None) -> BaseLLMProvider:
    cls = PROVIDERS.get(name)
    if cls is None:
        raise LLMError(
            f"Provedor '{name}' não suportado. Opções: {', '.join(PROVIDERS)}"
        )
    return cls(api_key=api_key, model=model)