"""
Utilitário avulso: lista os modelos do Gemini que a SUA chave de API
realmente tem acesso, com suporte a generateContent. Os nomes de modelo do
Gemini mudam com frequência (Pro fica indisponível no free tier, versões
são aposentadas, etc.), então o caminho confiável é sempre perguntar à
própria API, em vez de fixar um nome no código.

Uso:
    pip install google-genai
    python scripts/listar_modelos_google.py SUA_CHAVE_AQUI
"""
import sys

def main():
    if len(sys.argv) != 2:
        print("Uso: python listar_modelos_google.py SUA_CHAVE_DE_API")
        sys.exit(1)

    api_key = sys.argv[1]
    from google import genai

    client = genai.Client(api_key=api_key)
    print("Modelos disponíveis para esta chave (com suporte a generateContent):\n")
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None) or []
        if not actions or "generateContent" in actions:
            print(f"  - {m.name}")

if __name__ == "__main__":
    main()