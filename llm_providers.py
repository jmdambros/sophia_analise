"""
llm_providers.py
-----------------
Camada de abstração agnóstica de modelo de IA (Seção 11 do Documento de
Contexto): o Sophia não tem motor próprio, o usuário escolhe o provedor
(OpenAI, Anthropic, Google ou Groq) e fornece sua própria chave (BYOK).

Cada provedor implementa `generate(system_prompt, user_prompt, use_web_search, expect_json)`
e retorna texto bruto (JSON quando expect_json=True, validado depois em analysis.py;
texto livre quando expect_json=False, usado no chat de refinamento e na geração
de minutas de peças processuais).

Chaves de API NUNCA são logadas nem persistidas em disco por este módulo —
isso é responsabilidade da camada de armazenamento (ver app.py /
storage.py), que deve criptografá-las at-rest.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMError(RuntimeError):
    """Erro de comunicação com o provedor de IA escolhido pelo usuário."""


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
    ) -> str:
        """Retorna a resposta em texto (esperado: um único objeto JSON quando
        expect_json=True; texto livre quando expect_json=False)."""
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
    ) -> str:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise LLMError("Pacote 'openai' não instalado (pip install openai).") from e

        client = OpenAI(api_key=self.api_key)
        tools = [{"type": "web_search_preview"}] if use_web_search else []

        try:
            resp = client.responses.create(
                model=self.model,
                instructions=system_prompt,
                input=user_prompt,
                tools=tools or None,
            )
            return resp.output_text
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
    ) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("Pacote 'anthropic' não instalado (pip install anthropic).") from e

        client = anthropic.Anthropic(api_key=self.api_key)
        tools = [{"type": "web_search_20250305", "name": "web_search"}] if use_web_search else []

        try:
            resp = client.messages.create(
                model=self.model,
                max_tokens=4000,
                system=system_prompt,
                tools=tools or None,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
            return "\n".join(text_parts)
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
    ) -> str:
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
                ),
            )
            return resp.text
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
    ) -> str:
        try:
            from groq import Groq
        except ImportError:
            # Fallback para usar o pacote 'openai' com o endpoint do Groq
            try:
                from openai import OpenAI

                client = OpenAI(
                    base_url="https://api.groq.com/openai/v1",
                    api_key=self.api_key,
                )
            except ImportError as e:
                raise LLMError("Pacote 'groq' ou 'openai' não instalado (pip install groq).") from e
        else:
            client = Groq(api_key=self.api_key)

        try:
            # Nota: Groq não possui busca web nativa no Chat Completions básico
            kwargs = dict(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            # Só força JSON quando o chamador realmente espera JSON (análise
            # inicial). No chat de refinamento e na geração de minutas a
            # resposta deve ser texto livre — forçar json_object ali quebrava
            # essas duas features.
            if expect_json:
                kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
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