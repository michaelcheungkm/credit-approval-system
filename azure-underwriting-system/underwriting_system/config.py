from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class AzureOpenAIConfig:
    api_key: str
    azure_endpoint: str
    api_version: str
    chat_deployment: str
    embeddings_deployment: str | None
    temperature: float
    chroma_persist_dir: str


def load_config() -> AzureOpenAIConfig:
    """
    Loads config from environment variables (supports .env).
    """
    load_dotenv()

    api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "").strip() or "2024-10-21"
    chat_deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "").strip()
    embeddings_deployment = os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT", "").strip() or None
    # NOTE: some Azure chat models (e.g. certain gpt-5 deployments) only support the default temperature.
    # Use 1.0 by default to avoid unsupported_value errors.
    temperature_str = os.getenv("UNDERWRITING_TEMPERATURE", "1").strip()
    chroma_persist_dir = os.getenv("CHROMA_PERSIST_DIR", ".chroma").strip()

    if not api_key:
        raise RuntimeError("Missing AZURE_OPENAI_API_KEY")
    if not azure_endpoint:
        raise RuntimeError("Missing AZURE_OPENAI_ENDPOINT (e.g. https://<resource>.openai.azure.com/)")
    if not chat_deployment:
        raise RuntimeError("Missing AZURE_OPENAI_CHAT_DEPLOYMENT (this is your Azure deployment name)")

    try:
        temperature = float(temperature_str)
    except ValueError as e:
        raise RuntimeError("UNDERWRITING_TEMPERATURE must be a number") from e

    return AzureOpenAIConfig(
        api_key=api_key,
        azure_endpoint=azure_endpoint,
        api_version=api_version,
        chat_deployment=chat_deployment,
        embeddings_deployment=embeddings_deployment,
        temperature=temperature,
        chroma_persist_dir=chroma_persist_dir,
    )

